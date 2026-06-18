from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import yaml

from finix_restore.chunkers import LongStripChunker, PageChunker, TableGridChunker
from finix_restore.config import RunConfig
from finix_restore.dedup import DedupMerger
from finix_restore.finix_api import FinixApiClient, FinixApiError
from finix_restore.layout_sentry import LayoutSentry
from finix_restore.models import ChunkText, ImageProfile, LayoutHints, QualityReport
from finix_restore.normalizer import MarkdownNormalizer
from finix_restore.profiler import ImageProfiler
from finix_restore.quality_gate import IMAGE_SUFFIXES, QualityGate
from finix_restore.reading_order import ReadingOrderResolver
from finix_restore.submission import SubmissionWriter
from finix_restore.table_merger import TableMerger


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.profiler = ImageProfiler()
        self.layout_sentry = LayoutSentry()
        self.normalizer = MarkdownNormalizer()
        self.order_resolver = ReadingOrderResolver()
        self.dedup = DedupMerger(
            window_chars_long=int(config.merge.get("dedup_window_chars_long", 1200)),
            window_chars_table=int(config.merge.get("dedup_window_chars_table", 600)),
            similarity_threshold=float(config.merge.get("dedup_similarity_threshold", 0.88)),
        )
        self.table_merger = TableMerger()
        self.quality_gate = QualityGate(
            config.paths,
            max_duplication_ratio=float(config.quality.get("max_duplication_ratio", 0.18)),
            max_api_failure_ratio=float(config.quality.get("max_api_failure_ratio", 0.20)),
        )

    def run(self) -> QualityReport:
        self._write_config_snapshot()
        input_report = self.quality_gate.validate_input_files(self.config.input_dirs)
        if not input_report.passed:
            raise PipelineError(",".join(input_report.risks))

        image_paths = self._list_images(self.config.input_dirs)
        if self.config.limit is not None:
            image_paths = image_paths[: self.config.limit]

        rows: list[dict[str, str]] = []
        for image_path in image_paths:
            markdown = self._process_image(image_path)
            rows.append({"file_name": image_path.name, "ground_truth": markdown})

        return SubmissionWriter().write(rows, self.config.output_csv, [path.name for path in image_paths])

    def _process_image(self, image_path: Path) -> str:
        profile = self.profiler.profile_and_write(image_path, self.config.paths.profiles_dir)
        cached_merged = self._read_merged(profile.file_name)
        if cached_merged is not None and not self.config.dry_run:
            self.quality_gate.check_file(
                profile.file_name,
                cached_merged,
                profile.doc_type,
                chunk_count=0,
                failed_chunks=0,
            )
            return cached_merged

        hints = self.layout_sentry.analyze(image_path)
        chunks = self._chunk(profile, hints)

        if self.config.dry_run:
            markdown = ""
            self._write_merged(profile.file_name, markdown)
            self._write_dry_run_qc(profile, chunks_count=len(chunks))
            return markdown

        chunk_texts, failed_chunks = self._parse_chunks(chunks)
        normalized = self.normalizer.batch(chunk_texts)
        self._write_normalized(profile.file_name, normalized)
        ordered = self.order_resolver.resolve(normalized, doc_type=profile.doc_type)
        merged = self.dedup.merge(ordered)
        repaired = self.table_merger.repair(merged.markdown)
        markdown = repaired.markdown
        self._write_merged(profile.file_name, markdown)
        self.quality_gate.check_file(
            profile.file_name,
            markdown,
            profile.doc_type,
            chunk_count=len(chunks),
            failed_chunks=failed_chunks,
        )
        return markdown

    def _parse_chunks(self, chunks) -> tuple[list[ChunkText], int]:
        client = FinixApiClient(
            api_key=self.config.api_key,
            user_ids=self.config.user_ids,
            api_url=self.config.api_url,
            paths=self.config.paths,
            timeout_seconds=int(self.config.api.get("timeout_seconds", 240)),
            max_retries=int(self.config.api.get("max_retries", 3)),
            concurrency=int(self.config.api.get("concurrency", 1)),
            per_user_concurrency=int(self.config.api.get("per_user_concurrency", 1)),
        )
        results: list[ChunkText] = []
        failed_chunks = 0
        for chunk in chunks:
            try:
                results.append(client.parse_chunk(chunk, force_api=self.config.force_api))
            except FinixApiError as exc:
                if "authentication" in str(exc):
                    raise
                failed_chunks += 1
                results.append(
                    ChunkText(
                        chunk=chunk,
                        markdown="",
                        block_type="unknown",
                        source="api",
                    )
                )
        return results, failed_chunks

    def _chunk(self, profile: ImageProfile, hints: LayoutHints):
        chunk_cfg = self.config.chunk
        if profile.doc_type == "long_strip":
            chunker = LongStripChunker(
                self.config.paths.chunks_dir,
                window_height=int(chunk_cfg.get("long_window_height", 4000)),
                overlap=int(chunk_cfg.get("long_vertical_overlap", 320)),
            )
        else:
            cls = TableGridChunker if profile.doc_type == "table_page" else PageChunker
            chunker = cls(
                self.config.paths.chunks_dir,
                max_chunk_pixels=int(chunk_cfg.get("max_chunk_pixels", 12_000_000)),
                full_page_max_pixels=int(chunk_cfg.get("table_full_page_max_pixels", 16_000_000)),
                horizontal_overlap=int(chunk_cfg.get("table_horizontal_overlap", 160)),
                vertical_overlap=int(chunk_cfg.get("table_vertical_overlap", 220)),
            )
        return chunker.chunk(profile, hints)

    def _write_merged(self, file_name: str, markdown: str) -> None:
        self.config.paths.merged_dir.mkdir(parents=True, exist_ok=True)
        self._merged_path(file_name).write_text(markdown, encoding="utf-8")

    def _write_normalized(self, file_name: str, chunks: list[ChunkText]) -> None:
        out_dir = self.config.paths.normalized_dir / Path(file_name).stem
        out_dir.mkdir(parents=True, exist_ok=True)
        for chunk_text in chunks:
            (out_dir / f"{chunk_text.chunk.chunk_id}.md").write_text(chunk_text.markdown, encoding="utf-8")

    def _read_merged(self, file_name: str) -> str | None:
        if not self.config.resume or self.config.force_api:
            return None
        path = self._merged_path(file_name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _merged_path(self, file_name: str) -> Path:
        return self.config.paths.merged_dir / f"{Path(file_name).stem}.md"

    def _write_dry_run_qc(self, profile: ImageProfile, chunks_count: int) -> None:
        self.config.paths.qc_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "passed": True,
            "risks": [],
            "metrics": {
                "doc_type": profile.doc_type,
                "chunks": chunks_count,
                "dry_run": True,
            },
        }
        (self.config.paths.qc_dir / f"{Path(profile.file_name).stem}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_config_snapshot(self) -> None:
        self.config.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.config.paths.logs_dir / "config_snapshot.yaml").write_text(
            yaml.safe_dump(self.config.snapshot(), allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    def _list_images(self, input_dirs: Sequence[Path]) -> list[Path]:
        paths: list[Path] = []
        for input_dir in input_dirs:
            for path in sorted(Path(input_dir).iterdir(), key=lambda p: p.name):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    paths.append(path)
        return paths
