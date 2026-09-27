from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .fetch import is_on_date
from .models import NewsItem

GARBAGE_PATTERNS = [
    r"\b(video|podcast|quiz|live blog|photo gallery|newsletter sign.?up)\b",
    r"\b(opinion|editorial|commentary|sponsored|advertisement)\b",
    r"\bwhat to know\b",
    r"\bhow to\b",
    # Recurring programme/digest listings are containers for stories, not events.
    # Keep this deliberately narrow so ordinary articles mentioning a weekend survive.
    r"^(?:bloomberg\s+)?this weekend(?:\s+\d{1,2}/\d{1,2}/\d{2,4})?$",
]


def filter_items(
    items: list[NewsItem],
    run_date: str,
    timezone_name: str,
    config: dict,
    reference_time: str | None = None,
) -> tuple[list[NewsItem], dict[str, int]]:
    min_length = int(config.get("min_title_length", 12))
    keep_undated = bool(config.get("keep_undated", False))
    window_hours = float(config.get("window_hours", 0))
    window_start: datetime | None = None
    window_end: datetime | None = None
    if window_hours > 0:
        zone = ZoneInfo(timezone_name)
        reference = (
            datetime.fromisoformat(reference_time)
            if reference_time
            else datetime.now(timezone.utc)
        )
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        if reference.astimezone(zone).date().isoformat() == run_date:
            window_end = reference.astimezone(timezone.utc)
        else:
            next_day = date.fromisoformat(run_date) + timedelta(days=1)
            window_end = datetime.combine(next_day, time.min, tzinfo=zone).astimezone(
                timezone.utc
            )
        window_start = window_end - timedelta(hours=window_hours)
    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in GARBAGE_PATTERNS]
    kept: list[NewsItem] = []
    stats = {"input": len(items), "wrong_date": 0, "undated": 0, "short": 0, "garbage": 0}
    for item in items:
        if window_start is not None and window_end is not None and item.published_at:
            published = datetime.fromisoformat(item.published_at)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            date_match = window_start <= published.astimezone(timezone.utc) <= window_end
        else:
            date_match = is_on_date(item, run_date, timezone_name)
        if date_match is False:
            stats["wrong_date"] += 1
            continue
        if date_match is None:
            stats["undated"] += 1
            if not keep_undated:
                continue
        if len(item.title.strip()) < min_length:
            stats["short"] += 1
            continue
        if any(pattern.search(item.title) for pattern in patterns):
            stats["garbage"] += 1
            continue
        kept.append(item)
    stats["output"] = len(kept)
    return kept, stats
