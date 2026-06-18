from __future__ import annotations

import argparse

from finix_restore.config import ConfigError, load_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AFAC Task2 Finix document restore")
    parser.add_argument("--input_dir", action="append", required=True)
    parser.add_argument("--output_csv", required=True)
    parser.add_argument("--work_dir", default="outputs/run")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force_api", action="store_true")
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    from finix_restore.pipeline import Pipeline

    Pipeline(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
