from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .errors import NewsletterError
from .opencode_client import client_from_config
from .incremental import run_auto_pipeline
from .storage import RunContext, RunLock

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _date_value(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows-first private daily newsletter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run or resume the complete pipeline")
    run.add_argument("--date", type=_date_value, default=None)
    run.add_argument("--config", type=Path, default=PROJECT_ROOT / "config")
    run.add_argument("--resume", metavar="RUN_ID")
    run.add_argument("--full", action="store_true", help="force a full run even if today has a baseline")

    doctor = subparsers.add_parser("doctor", help="check configuration and OpenCode health")
    doctor.add_argument("--config", type=Path, default=PROJECT_ROOT / "config")

    unlock = subparsers.add_parser("unlock", help="remove a stale run lock after checking no run exists")
    unlock.add_argument("--config", type=Path, default=PROJECT_ROOT / "config")
    return parser


def _configure_logging(log_path: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_dir = Path(args.config).resolve()
    _configure_logging(config_dir.parent / "logs" / "bootstrap.log")
    try:
        config = load_config(config_dir)
        if args.command == "doctor":
            health = client_from_config(
                dict(config.pipeline.get("opencode") or {}), config.root
            ).health()
            print(json.dumps({"config": "ok", "opencode": health}, ensure_ascii=False, indent=2))
            return 0

        lock_path = config.paths["runs"] / ".newsletter.lock"
        if args.command == "unlock":
            if lock_path.exists():
                details = lock_path.read_text(encoding="utf-8", errors="replace")
                lock_path.unlink()
                print(f"removed stale lock: {lock_path}\nprevious owner: {details}")
            else:
                print(f"no lock exists: {lock_path}")
            return 0

        with RunLock(lock_path):
            run_date = args.date or datetime.now(ZoneInfo(config.timezone)).date().isoformat()
            context = (
                RunContext.resume(config.paths["runs"], run_date, args.resume, config.config_hash)
                if args.resume
                else RunContext.create(config.paths["runs"], run_date, config.config_hash)
            )
            _configure_logging(config.paths["logs"] / f"{context.run_id}.log")
            result = run_auto_pipeline(context, config, force_full=bool(args.full or args.resume))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except NewsletterError as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 2
    except Exception:
        logging.getLogger(__name__).exception("unexpected failure")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
