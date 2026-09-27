from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = 1


@dataclass(slots=True)
class SourceRef:
    source_id: str
    name: str
    url: str
    weight: float = 0.5
    provider: str = "rss"
    access_type: str = "free"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRef":
        return cls(**data)


@dataclass(slots=True)
class NewsItem:
    item_id: str
    title: str
    summary: str
    language: str
    tags: list[str]
    published_at: str | None
    published_raw: str | None
    sources: list[SourceRef]
    image_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NewsItem":
        payload = dict(data)
        payload.pop("schema_version", None)
        payload["sources"] = [SourceRef.from_dict(x) for x in payload.get("sources", [])]
        return cls(**payload)


@dataclass(slots=True)
class EventGroup:
    event_id: str
    group_type: str
    leader_item_id: str
    items: list[NewsItem]
    max_similarity: float = 0.0

    @property
    def leader(self) -> NewsItem:
        for item in self.items:
            if item.item_id == self.leader_item_id:
                return item
        raise KeyError(f"leader not found: {self.leader_item_id}")

    @property
    def source_count(self) -> int:
        return len({src.source_id for item in self.items for src in item.sources})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.event_id,
            "group_type": self.group_type,
            "leader_item_id": self.leader_item_id,
            "items": [item.to_dict() for item in self.items],
            "max_similarity": self.max_similarity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventGroup":
        return cls(
            event_id=data["event_id"],
            group_type=data["group_type"],
            leader_item_id=data["leader_item_id"],
            items=[NewsItem.from_dict(x) for x in data["items"]],
            max_similarity=float(data.get("max_similarity", 0.0)),
        )


@dataclass(slots=True)
class RankedEvent:
    event_id: str
    importance_score: float
    interest_score: int
    confidence: int
    reason: str
    rule_score: float = 0.0

    @property
    def final_score(self) -> float:
        # Personal interests are supplied to the editor as a secondary reference.
        # The stored score is already the source/corroboration-adjusted importance.
        return round(float(self.importance_score), 2)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["final_score"] = self.final_score
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RankedEvent":
        payload = dict(data)
        payload.pop("final_score", None)
        return cls(**payload)


@dataclass(slots=True)
class Translation:
    item_id: str
    title_zh: str
    summary_zh: str
    title_provider: str
    summary_provider: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Translation":
        return cls(**data)
