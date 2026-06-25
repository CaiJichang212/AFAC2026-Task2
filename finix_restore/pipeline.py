from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence

import yaml

from finix_restore.chunkers import LongStripChunker, PageChunker, TableGridChunker
from finix_restore.concurrency import ApiConcurrencyLimiter
from finix_restore.config import RunConfig
from finix_restore.dedup import DedupMerger
from finix_restore.finix_api import FinixApiClient
from finix_restore.layout_sentry import LayoutSentry
from finix_restore.long_merger import LongStripMerger
from finix_restore.models import Chunk, ChunkText, ImageProfile, LayoutHints, ProcessedFile, QualityReport
from finix_restore.normalizer import MarkdownNormalizer
from finix_restore.profiler import ImageProfiler
from finix_restore.quality_gate import IMAGE_SUFFIXES, QualityGate
from finix_restore.reading_order import ReadingOrderResolver
from finix_restore.retry_planner import RetryPlanner
from finix_restore.submission import SubmissionWriter
from finix_restore.table_assembler import TableRowAssembler
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
        self.run_id = uuid.uuid4().hex[:12]
        self.dedup = DedupMerger(
            window_chars_long=int(config.merge.get("dedup_window_chars_long", 1200)),
            window_chars_table=int(config.merge.get("dedup_window_chars_table", 600)),
            similarity_threshold=float(config.merge.get("dedup_similarity_threshold", 0.88)),
        )
        self.long_merger = LongStripMerger(dedup=self.dedup)
        self.table_merger = TableMerger()
        self.table_assembler = TableRowAssembler()
        self.quality_gate = QualityGate(
            config.paths,
            max_duplication_ratio=float(config.quality.get("max_duplication_ratio", 0.18)),
            max_api_failure_ratio=float(config.quality.get("max_api_failure_ratio", 0.20)),
        )
        self.retry_planner = RetryPlanner(max_reruns_per_file=int(config.quality.get("max_reruns_per_file", 2)))
        self.api_limiter = ApiConcurrencyLimiter(
            global_concurrency=int(config.api.get("concurrency", 1)),
            user_ids=config.user_ids,
            per_user_concurrency=int(config.api.get("per_user_concurrency", 1)),
        )
        self.log_lock = threading.Lock()

    def run(self) -> QualityReport:
        self._write_config_snapshot()
        self._remove_stale_output_csv()
        input_report = self.quality_gate.validate_input_files(self.config.input_dirs)
        if not input_report.passed:
            raise PipelineError(",".join(input_report.risks))

        image_paths = self._list_images(self.config.input_dirs)
        image_concurrency = max(1, int(self.config.runtime.get("image_concurrency", 1)))
        processed_files: list[ProcessedFile | None] = [None] * len(image_paths)
        rows: list[dict[str, str] | None] = [None] * len(image_paths)

        if image_concurrency <= 1:
            for index, image_path in enumerate(image_paths):
                processed = self._process_image(image_path)
                processed_files[index] = processed
                rows[index] = {"file_name": image_path.name, "ground_truth": processed.markdown}
        else:
            with ThreadPoolExecutor(max_workers=image_concurrency) as executor:
                future_to_index = {
                    executor.submit(self._process_image, image_path): index
                    for index, image_path in enumerate(image_paths)
                }
                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    image_path = image_paths[index]
                    processed = future.result()
                    processed_files[index] = processed
                    rows[index] = {"file_name": image_path.name, "ground_truth": processed.markdown}

        if any(item is None for item in processed_files) or any(item is None for item in rows):
            raise PipelineError("internal error: incomplete parallel image results")
        final_processed = [item for item in processed_files if item is not None]
        final_rows = [item for item in rows if item is not None]

        summary = self.quality_gate.write_run_summary(
            final_processed,
            output_csv=None if self.config.dry_run else self.config.output_csv,
            dry_run=self.config.dry_run,
        )
        if not self.config.dry_run and not summary["passed"]:
            raise PipelineError("quality gate failed")
        return SubmissionWriter().write(final_rows, self.config.output_csv, [path.name for path in image_paths])

    def _process_image(self, image_path: Path) -> ProcessedFile:
        profile = self.profiler.profile_and_write(image_path, self.config.paths.profiles_dir)
        cached_merged = self._read_merged(profile.file_name)
        if cached_merged is not None and not self.config.dry_run:
            quality = self.quality_gate.check_file(
                profile.file_name,
                cached_merged,
                profile.doc_type,
                chunk_count=0,
                failed_chunks=0,
                extra_metrics={"from_merged_cache": 1},
            )
            return ProcessedFile(
                file_name=profile.file_name,
                markdown=cached_merged,
                quality=quality,
                rerun_count=0,
            )

        hints = self.layout_sentry.analyze(image_path, chunk_config=self.config.chunk)
        chunks = self._chunk(profile, hints)

        if self.config.dry_run:
            markdown = ""
            self._write_merged(profile.file_name, markdown)
            self._write_dry_run_qc(profile, chunks)
            quality = QualityReport(
                passed=True,
                risks=[],
                metrics={"doc_type": profile.doc_type, "chunks": len(chunks), "dry_run": True},
            )
            return ProcessedFile(file_name=profile.file_name, markdown=markdown, quality=quality, rerun_count=0)

        rerun_count = 0
        force_api = self.config.force_api
        concurrency_override: int | None = None
        while True:
            markdown, failed_chunks, extra_metrics = self._process_image_once(
                chunks,
                profile,
                force_api=force_api,
                concurrency_override=concurrency_override,
            )
            quality = self.quality_gate.check_file(
                profile.file_name,
                markdown,
                profile.doc_type,
                chunk_count=len(chunks),
                failed_chunks=failed_chunks,
                extra_metrics=extra_metrics,
            )
            plan = self.retry_planner.plan(quality, rerun_count=rerun_count)
            if quality.passed or not plan["rerun"]:
                return ProcessedFile(
                    file_name=profile.file_name,
                    markdown=markdown,
                    quality=quality,
                    rerun_count=rerun_count,
                )
            rerun_count += 1
            force_api = bool(plan["force_api"])
            planned_concurrency = int(plan["concurrency"])
            concurrency_override = planned_concurrency if planned_concurrency > 0 else None

    def _process_image_once(
        self,
        chunks,
        profile: ImageProfile,
        force_api: bool = False,
        concurrency_override: int | None = None,
    ) -> tuple[str, int, dict[str, float | int | str]]:
        chunk_texts, failed_chunks = self._parse_chunks(
            chunks,
            force_api=force_api,
            concurrency_override=concurrency_override,
        )
        normalized = self.normalizer.batch(chunk_texts)
        self._write_normalized(profile.file_name, normalized)
        ordered = self.order_resolver.resolve(normalized, doc_type=profile.doc_type)
        extra_metrics: dict[str, float | int | str] = self._long_cutline_metrics(chunks, profile.doc_type)
        if profile.doc_type == "table_page":
            assembled = self.table_assembler.assemble(ordered)
            repaired = self.table_merger.repair(assembled.markdown)
            extra_metrics["table_assembled_tables"] = assembled.assembled_tables
            extra_metrics["table_assembly_warning_count"] = len(assembled.warnings)
            if assembled.warnings:
                extra_metrics["table_assembly_warnings"] = ",".join(assembled.warnings)
        elif profile.doc_type == "long_strip":
            merged = self.long_merger.merge(ordered)
            repaired = self.table_merger.repair(merged.markdown)
            extra_metrics["long_merged_tables"] = merged.merged_tables
            extra_metrics["long_removed_table_fragments"] = merged.removed_table_fragments
            extra_metrics["long_merge_warning_count"] = len(merged.warnings)
            extra_metrics["long_removed_text_blocks"] = merged.removed_text_blocks
            if merged.warnings:
                extra_metrics["long_merge_warnings"] = ",".join(merged.warnings)
        else:
            merged = self.dedup.merge(ordered)
            repaired = self.table_merger.repair(merged.markdown)
        extra_metrics["table_repaired_tags"] = repaired.repaired_tags
        markdown = repaired.markdown
        self._write_merged(profile.file_name, markdown)
        return markdown, failed_chunks, extra_metrics

    def _parse_chunks(
        self,
        chunks,
        force_api: bool = False,
        concurrency_override: int | None = None,
    ) -> tuple[list[ChunkText], int]:
        worker_concurrency = self._chunk_worker_concurrency(concurrency_override)
        client = FinixApiClient(
            api_key=self.config.api_key,
            user_ids=self.config.user_ids,
            api_url=self.config.api_url,
            paths=self.config.paths,
            timeout_seconds=int(self.config.api.get("timeout_seconds", 240)),
            max_retries=int(self.config.api.get("max_retries", 3)),
            concurrency=worker_concurrency,
            per_user_concurrency=int(self.config.api.get("per_user_concurrency", 1)),
            run_id=self.run_id,
            limiter=self.api_limiter,
            log_lock=self.log_lock,
        )
        return client.parse_chunks(chunks, force_api=force_api)

    def _chunk_worker_concurrency(self, concurrency_override: int | None = None) -> int:
        if concurrency_override is not None:
            return max(1, int(concurrency_override))
        global_limit = max(1, int(self.config.api.get("concurrency", 1)))
        image_concurrency = max(1, int(self.config.runtime.get("image_concurrency", 1)))
        if image_concurrency <= 1:
            return global_limit
        return max(1, min(global_limit, (global_limit + image_concurrency - 1) // image_concurrency))

    def _chunk(self, profile: ImageProfile, hints: LayoutHints):
        if profile.doc_type == "long_strip":
            chunker = LongStripChunker(
                self.config.paths.chunks_dir,
                config=self.config.chunk,
            )
        elif profile.doc_type == "table_page":
            chunker = TableGridChunker(
                self.config.paths.chunks_dir,
                config=self.config.chunk,
            )
        else:
            chunker = PageChunker(
                self.config.paths.chunks_dir,
                config=self.config.chunk,
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
        text = path.read_text(encoding="utf-8")
        # 空的 merged 往往来自上一轮 API 全失败/崩溃, 不应作为有效缓存复用,
        # 否则 resume 会永久跳过该图, 无法自愈。
        if not text.strip():
            return None
        return text

    def _merged_path(self, file_name: str) -> Path:
        return self.config.paths.merged_dir / f"{Path(file_name).stem}.md"

    def _write_dry_run_qc(self, profile: ImageProfile, chunks: Sequence[Chunk]) -> None:
        self.config.paths.qc_dir.mkdir(parents=True, exist_ok=True)
        chunk_policy = {
            "long_strip": "long_dynamic_v1",
            "table_page": "table_grid_v2",
            "normal_page": "normal_page_v1",
        }.get(profile.doc_type, "unknown")
        max_chunk_pixels = max((c.chunk_pixels for c in chunks), default=0)
        over_safe = sum(1 for c in chunks if "over_safe_pixels" in c.risk_flags)
        over_hard = sum(1 for c in chunks if c.chunk_pixels > self.config.chunk.hard_max_pixels)
        metrics = {
            "doc_type": profile.doc_type,
            "chunks": len(chunks),
            "dry_run": True,
            "chunk_policy": chunk_policy,
            "max_chunk_pixels": max_chunk_pixels,
            "over_safe_chunks": over_safe,
            "over_hard_chunks": over_hard,
        }
        metrics.update(self._long_cutline_metrics(chunks, profile.doc_type))
        payload = {
            "passed": True,
            "risks": [],
            "metrics": metrics,
        }
        (self.config.paths.qc_dir / f"{Path(profile.file_name).stem}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _long_cutline_metrics(
        self,
        chunks: Sequence[Chunk],
        doc_type: str,
    ) -> dict[str, float | int]:
        if doc_type != "long_strip":
            return {}

        blank_cut_count = 0
        fixed_cut_count = 0
        last_index = len(chunks) - 1
        for index, chunk in enumerate(chunks):
            if index == last_index or chunk.is_last_row:
                continue
            if chunk.cut_source == "blank_band":
                blank_cut_count += 1
            else:
                fixed_cut_count += 1

        total = blank_cut_count + fixed_cut_count
        return {
            "blank_cut_count": blank_cut_count,
            "fixed_cut_count": fixed_cut_count,
            "blank_cut_ratio": blank_cut_count / max(1, total),
        }

    def _write_config_snapshot(self) -> None:
        self.config.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.config.paths.logs_dir / "config_snapshot.yaml").write_text(
            yaml.safe_dump(self.config.snapshot(), allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    def _list_images(self, input_dirs: Sequence[Path]) -> list[Path]:
        paths: list[Path] = []
        for input_dir in input_dirs:
            dir_paths: list[Path] = []
            for path in sorted(Path(input_dir).iterdir(), key=lambda p: p.name):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    dir_paths.append(path)
            if self.config.limit_per_dir is not None:
                dir_paths = dir_paths[: self.config.limit_per_dir]
            paths.extend(dir_paths)
        if self.config.limit is not None:
            paths = paths[: self.config.limit]
        return paths

    def _remove_stale_output_csv(self) -> None:
        if self.config.dry_run:
            return
        self.config.output_csv.unlink(missing_ok=True)
