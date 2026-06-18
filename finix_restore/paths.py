from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunPaths:
    work_dir: Path
    profiles_dir: Path
    chunks_dir: Path
    api_raw_dir: Path
    normalized_dir: Path
    merged_dir: Path
    qc_dir: Path
    logs_dir: Path
    metrics_dir: Path

    @classmethod
    def from_work_dir(cls, work_dir: Path) -> "RunPaths":
        work_dir = Path(work_dir)
        paths = cls(
            work_dir=work_dir,
            profiles_dir=work_dir / "profiles",
            chunks_dir=work_dir / "chunks",
            api_raw_dir=work_dir / "api_raw",
            normalized_dir=work_dir / "normalized",
            merged_dir=work_dir / "merged",
            qc_dir=work_dir / "qc",
            logs_dir=work_dir / "logs",
            metrics_dir=work_dir / "metrics",
        )
        for path in (
            paths.work_dir,
            paths.profiles_dir,
            paths.chunks_dir,
            paths.api_raw_dir,
            paths.normalized_dir,
            paths.merged_dir,
            paths.qc_dir,
            paths.logs_dir,
            paths.metrics_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return paths
