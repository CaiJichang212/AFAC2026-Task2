from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
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
    runtime: dict[str, int] = field(default_factory=lambda: {"image_concurrency": 1})

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, ChunkConfig):
            object.__setattr__(self, "chunk", ChunkConfig.from_mapping(self.chunk))

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_dirs"] = [str(p) for p in self.input_dirs]
        payload["output_csv"] = str(self.output_csv)
        payload["paths"] = {k: str(v) for k, v in asdict(self.paths).items()}
        payload["api_key"] = "***"
        payload["user_ids"] = ["***" for _ in self.user_ids]
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
    effective_concurrency = min(requested, max(1, len(user_ids) * per_user))
    api["concurrency"] = effective_concurrency
    api["per_user_concurrency"] = per_user
    # 让"配置了但被 cap"这类问题在启动时可见, 避免看着 25 实际只有 5 的误判。
    api["requested_concurrency"] = requested
    api["effective_concurrency"] = effective_concurrency
    api["user_count"] = len(user_ids)
    if effective_concurrency < requested and not dry_run:
        import sys

        print(
            "[finix_restore] WARNING: api.concurrency={requested} is capped to {effective} "
            "by user_ids ({n}) * per_user_concurrency ({p}). "
            "Increase FINIX_USER_IDS or per_user_concurrency to raise real throughput.".format(
                requested=requested,
                effective=effective_concurrency,
                n=len(user_ids),
                p=per_user,
            ),
            file=sys.stderr,
        )

    runtime_raw = raw.get("runtime") or {}
    runtime = {"image_concurrency": int(runtime_raw.get("image_concurrency", 1))}
    cli_image_concurrency = getattr(args, "image_concurrency", None)
    if cli_image_concurrency is not None:
        runtime["image_concurrency"] = int(cli_image_concurrency)
    if runtime["image_concurrency"] < 1:
        raise ConfigError("runtime.image_concurrency must be >= 1")

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
        runtime=runtime,
    )
