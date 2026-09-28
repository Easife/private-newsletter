from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .errors import ConfigurationError


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"missing configuration file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"configuration root must be an object: {path}")
    return value


def _canonicalize(value: Any) -> Any:
    """Normalize representation-only differences before hashing configuration."""
    if isinstance(value, dict):
        return {key: _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@dataclass(frozen=True, slots=True)
class AppConfig:
    root: Path
    config_dir: Path
    pipeline: dict[str, Any]
    sources: list[dict[str, Any]]
    interests: dict[str, list[str]]
    terminology: dict[str, str]
    config_hash: str

    @property
    def timezone(self) -> str:
        return str(self.pipeline.get("timezone", "Asia/Shanghai"))

    @property
    def paths(self) -> dict[str, Path]:
        raw = self.pipeline.get("paths", {})
        return {
            name: (self.root / raw.get(name, default)).resolve()
            for name, default in {
                "runs": "runs",
                "archive": "archive",
                "latest": "latest",
                "logs": "logs",
            }.items()
        }


def load_config(config_dir: str | Path) -> AppConfig:
    config_path = Path(config_dir).resolve()
    pipeline = _read_yaml(config_path / "pipeline.yaml")
    sources_doc = _read_yaml(config_path / "sources.yaml")
    interests_doc = _read_yaml(config_path / "interests.yaml")
    terminology_doc = _read_yaml(config_path / "terminology.yaml")

    sources = sources_doc.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise ConfigurationError("sources.yaml must contain a non-empty sources list")
    seen: set[str] = set()
    for source in sources:
        source_id = str(source.get("id", "")).strip()
        if not source_id or source_id in seen:
            raise ConfigurationError(f"source id is empty or duplicated: {source_id!r}")
        seen.add(source_id)
        provider = source.get("provider", "rss")
        if provider not in {"rss", "google_news"}:
            raise ConfigurationError(f"unsupported source provider: {provider}")
        required = "rss_url" if provider == "rss" else "search"
        if not source.get(required):
            raise ConfigurationError(f"source {source_id} requires {required}")

    interests = {
        "long_term": list(interests_doc.get("long_term") or []),
        "recent": list(interests_doc.get("recent") or []),
    }
    terminology = dict(terminology_doc.get("terms") or {})

    timezone_name = str(pipeline.get("timezone", "Asia/Shanghai"))
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(
            f"unknown timezone {timezone_name!r}; install the tzdata package on Windows"
        ) from exc

    canonical = json.dumps(
        _canonicalize({
            "pipeline": pipeline,
            "sources": sources,
            # recent interests are deliberately one-shot. They affect the next model
            # request but not cache compatibility after being consumed.
            "interests": {"long_term": interests["long_term"]},
            "terminology": terminology,
        }),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    config_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return AppConfig(
        root=config_path.parent,
        config_dir=config_path,
        pipeline=pipeline,
        sources=sources,
        interests=interests,
        terminology=terminology,
        config_hash=config_hash,
    )
