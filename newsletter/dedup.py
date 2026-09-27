from __future__ import annotations

import hashlib
import re

from .fetch import normalize_title
from .models import EventGroup, NewsItem

STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "from", "to", "for", "with", "by", "of",
    "and", "or", "but", "is", "are", "was", "were", "has", "have", "will", "says",
}


def _tokens(title: str) -> set[str]:
    normalized = normalize_title(title)
    words = {word for word in re.findall(r"[a-z0-9]{2,}", normalized) if word not in STOPWORDS}
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    ngrams = {chinese[i : i + 2] for i in range(max(0, len(chinese) - 1))}
    return words | ngrams


def similarity(left: NewsItem, right: NewsItem) -> float:
    a, b = _tokens(left.title), _tokens(right.title)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _leader(items: list[NewsItem]) -> NewsItem:
    return max(
        items,
        key=lambda item: (
            max((source.weight for source in item.sources), default=0.0),
            len(item.summary),
            item.published_at or "",
            item.item_id,
        ),
    )


def _event_id(items: list[NewsItem]) -> str:
    identity = "|".join(sorted(item.item_id for item in items))
    return "event_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def group_events(
    items: list[NewsItem], exact_threshold: float = 0.72, related_threshold: float = 0.34
) -> tuple[list[EventGroup], dict[str, int]]:
    # Greedy representative grouping avoids Union-Find's transitive chain explosions.
    buckets: list[list[NewsItem]] = []
    bucket_max: list[float] = []
    for item in items:
        best_index = -1
        best_score = 0.0
        for index, bucket in enumerate(buckets):
            score = similarity(item, _leader(bucket))
            if score > best_score:
                best_index, best_score = index, score
        if best_index >= 0 and best_score >= related_threshold:
            buckets[best_index].append(item)
            bucket_max[best_index] = max(bucket_max[best_index], best_score)
        else:
            buckets.append([item])
            bucket_max.append(0.0)

    groups: list[EventGroup] = []
    for bucket, max_score in zip(buckets, bucket_max):
        leader = _leader(bucket)
        if len(bucket) == 1:
            group_type = "single"
        elif max_score >= exact_threshold:
            group_type = "exact_match"
        else:
            group_type = "related"
        ordered = [leader] + sorted(
            (item for item in bucket if item.item_id != leader.item_id),
            key=lambda item: item.item_id,
        )
        groups.append(
            EventGroup(
                event_id=_event_id(ordered),
                group_type=group_type,
                leader_item_id=leader.item_id,
                items=ordered,
                max_similarity=round(max_score, 4),
            )
        )
    groups.sort(key=lambda group: (group.leader.published_at or "", group.event_id), reverse=True)
    stats = {
        "input": len(items),
        "events": len(groups),
        "single": sum(group.group_type == "single" for group in groups),
        "exact_match": sum(group.group_type == "exact_match" for group in groups),
        "related": sum(group.group_type == "related" for group in groups),
    }
    return groups, stats
