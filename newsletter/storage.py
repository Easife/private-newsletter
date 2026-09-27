from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .errors import LockError, StageError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def application_fingerprint() -> str:
    digest = hashlib.sha256()
    package_dir = Path(__file__).resolve().parent
    for path in sorted(package_dir.glob("*.py"), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class RunLock(AbstractContextManager["RunLock"]):
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: int | None = None

    def __enter__(self) -> "RunLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            details = self.lock_path.read_text(encoding="utf-8", errors="replace")
            raise LockError(f"another run owns {self.lock_path}: {details.strip()}") from exc
        payload = json.dumps({"pid": os.getpid(), "created_at": utc_now()}, ensure_ascii=False)
        os.write(self._fd, payload.encode("utf-8"))
        os.fsync(self._fd)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


@dataclass(slots=True)
class RunContext:
    run_date: str
    run_id: str
    run_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]

    @classmethod
    def create(cls, runs_root: Path, run_date: str, config_hash: str) -> "RunContext":
        stamp = datetime.now().strftime("%H%M%S-%f")
        run_id = f"{run_date}-{stamp}-{os.getpid()}"
        run_dir = runs_root / run_date / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest_path = run_dir / "manifest.json"
        manifest = {
            "schema_version": 1,
            "app_version": __version__,
            "app_fingerprint": application_fingerprint(),
            "run_id": run_id,
            "run_date": run_date,
            "config_hash": config_hash,
            "status": "running",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "stages": {},
        }
        context = cls(run_date, run_id, run_dir, manifest_path, manifest)
        context.save_manifest()
        return context

    @classmethod
    def resume(
        cls, runs_root: Path, run_date: str, run_id: str, config_hash: str
    ) -> "RunContext":
        run_dir = runs_root / run_date / run_id
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            raise StageError("resume", f"manifest not found: {manifest_path}")
        manifest = read_json(manifest_path)
        if manifest.get("run_date") != run_date:
            raise StageError("resume", "run date does not match manifest")
        if manifest.get("app_version") != __version__:
            raise StageError("resume", "application version changed; start a new run")
        if manifest.get("app_fingerprint") != application_fingerprint():
            raise StageError("resume", "application code changed; start a new run")
        if manifest.get("config_hash") != config_hash:
            raise StageError("resume", "configuration changed; start a new run")
        manifest["status"] = "running"
        context = cls(run_date, run_id, run_dir, manifest_path, manifest)
        context.save_manifest()
        return context

    def save_manifest(self) -> None:
        self.manifest["updated_at"] = utc_now()
        atomic_write_json(self.manifest_path, self.manifest)

    def stage_completed(self, name: str, artifact: str) -> bool:
        record = self.manifest.get("stages", {}).get(name, {})
        return record.get("status") == "complete" and (self.run_dir / artifact).is_file()

    def begin_stage(self, name: str) -> None:
        self.manifest.setdefault("stages", {})[name] = {
            "status": "running",
            "started_at": utc_now(),
        }
        self.save_manifest()

    def complete_stage(self, name: str, artifact: str, **metadata: Any) -> None:
        self.manifest["stages"][name] = {
            "status": "complete",
            "completed_at": utc_now(),
            "artifact": artifact,
            **metadata,
        }
        self.save_manifest()

    def fail(self, stage: str, error: str) -> None:
        self.manifest["status"] = "failed"
        self.manifest["error"] = {"stage": stage, "message": error, "at": utc_now()}
        self.manifest.setdefault("stages", {}).setdefault(stage, {})["status"] = "failed"
        self.save_manifest()

    def finish(self) -> None:
        self.manifest["status"] = "complete"
        self.manifest["completed_at"] = utc_now()
        self.save_manifest()
