from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from dotenv import load_dotenv

from finix_restore.chunk_config import ChunkConfig
from finix_restore.paths import RunPaths


DEFAULT_API_URL = "https://finixdocapi.alipay.com/api/finix_doc/call_with_file"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RunConfig:
    input_dirs: list[Path]
    output_csv: Path
    paths: RunPaths
    api_key: str
    user_ids: list[str]
    api_url: str
    api: dict[str, int | str]
    chunk: ChunkConfig | Mapping[str, Any]
    merge: dict[str, float | int]
    quality: dict[str, float | int]
    resume: bool = True
    force_api: bool = False
    dry_run: bool = False
    limit: int | None = None
    limit_per_dir: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, ChunkConfig):
            object.__setattr__(self, "chunk", ChunkConfig.from_mapping(self.chunk))

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_dirs"] = [str(p) for p in self.input_dirs]
        payload["output_csv"] = str(self.output_csv)
        payload["paths"] = {k: str(v) for k, v in asdict(self.paths).items()}
        payload["api_key"] = "***"
        payload["chunk"] = self.chunk.to_dict()
        return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_user_ids(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def load_config(args) -> RunConfig:
    load_dotenv()
    config_path = Path(args.config)
    raw = _read_yaml(config_path)

    dry_run = bool(args.dry_run)
    api_key = (os.getenv("FINIX_API_KEY") or os.getenv("apiKey") or "").strip()
    if not api_key and not dry_run:
        raise ConfigError("FINIX_API_KEY is required")
    user_ids = _parse_user_ids(os.getenv("FINIX_USER_IDS") or os.getenv("userIds"))
    if not user_ids and not dry_run:
        raise ConfigError("FINIX_USER_IDS is required")
    if dry_run and not user_ids:
        user_ids = ["dry_run"]

    input_dirs = [Path(p) for p in args.input_dir]
    for input_dir in input_dirs:
        if not input_dir.exists() or not input_dir.is_dir():
            raise ConfigError(f"input_dir is not a directory: {input_dir}")

    api = dict(raw.get("api", {}))
    env_url = (os.getenv("FINIX_API_URL") or os.getenv("apiUrl") or "").strip()
    api_url = env_url or api.get("url") or DEFAULT_API_URL
    if api_url == "${FINIX_API_URL}":
        api_url = DEFAULT_API_URL
    api["url"] = api_url
    per_user = int(api.get("per_user_concurrency", 1))
    requested = int(api.get("concurrency", 1))
    api["concurrency"] = min(requested, max(1, len(user_ids) * per_user))
    api["per_user_concurrency"] = per_user

    return RunConfig(
        input_dirs=input_dirs,
        output_csv=Path(args.output_csv),
        paths=RunPaths.from_work_dir(Path(args.work_dir)),
        api_key=api_key,
        user_ids=user_ids,
        api_url=api_url,
        api=api,
        chunk=ChunkConfig.from_mapping(raw.get("chunk", {})),
        merge=dict(raw.get("merge", {})),
        quality=dict(raw.get("quality", {})),
        resume=bool(args.resume),
        force_api=bool(args.force_api),
        dry_run=dry_run,
        limit=args.limit,
        limit_per_dir=args.limit_per_dir,
    )
