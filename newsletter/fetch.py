from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

from .models import NewsItem, SourceRef

logger = logging.getLogger(__name__)

GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"
)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def _clean_text(value: str) -> str:
    if "<" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", value).strip()


def canonicalize_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"}:
            return ""
        query = [
            (key, item)
            for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
        ]
        return urllib.parse.urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, urllib.parse.urlencode(query), "")
        )
    except Exception:
        return ""


def normalize_title(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.casefold()).strip()


def stable_item_id(source_id: str, url: str, title: str) -> str:
    identity = f"{source_id}|{canonicalize_url(url)}|{normalize_title(title)}"
    return "item_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def normalize_published(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        pass
    if parsed is None:
        iso_value = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _image_from_entry(entry: Any) -> str | None:
    candidates: list[tuple[int, str]] = []
    for media in entry.get("media_content", []) or []:
        url = canonicalize_url(str(media.get("url", "")))
        if url and media.get("medium", "image") == "image":
            try:
                width = int(media.get("width", 0))
            except (TypeError, ValueError):
                width = 0
            candidates.append((width, url))
    for media in entry.get("media_thumbnail", []) or []:
        url = canonicalize_url(str(media.get("url", "")))
        if url:
            candidates.append((0, url))
    for enclosure in entry.get("enclosures", []) or []:
        if str(enclosure.get("type", "")).startswith("image/"):
            url = canonicalize_url(str(enclosure.get("href") or enclosure.get("url") or ""))
            if url:
                candidates.append((0, url))
    return max(candidates, default=(0, ""))[1] or None


def fetch_source(
    source: dict[str, Any], timeout: float, verify_tls: bool, proxies: dict[str, str] | None
) -> tuple[list[NewsItem], dict[str, Any]]:
    source_id = str(source["id"])
    provider = str(source.get("provider", "rss"))
    if provider == "google_news":
        request_url = GOOGLE_NEWS_URL.format(
            query=urllib.parse.quote(str(source.get("search", ""))),
            hl=urllib.parse.quote(str(source.get("google_hl", "en-US"))),
            gl=urllib.parse.quote(str(source.get("google_gl", "US"))),
            ceid=urllib.parse.quote(str(source.get("google_ceid", "US:en"))),
        )
    else:
        request_url = str(source["rss_url"])

    status: dict[str, Any] = {"source_id": source_id, "name": source["name"], "ok": False}
    try:
        response = requests.get(
            request_url,
            timeout=timeout,
            verify=verify_tls,
            proxies=proxies,
            headers={"User-Agent": "PrivateNewsletter/2.0 (+Windows automation)"},
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"feed parse failed: {feed.bozo_exception}")
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        return [], status

    items: list[NewsItem] = []
    for entry in feed.entries:
        title = _clean_text(str(entry.get("title", "")))
        if not title:
            continue
        summary = _clean_text(str(entry.get("summary", entry.get("description", ""))))[:1000]
        url = canonicalize_url(str(entry.get("link", "")))
        raw_published = entry.get("published", entry.get("updated"))
        source_ref = SourceRef(
            source_id=source_id,
            name=str(source["name"]),
            url=url,
            weight=float(source.get("weight", 0.5)),
            provider=provider,
            access_type=str(source.get("access_type", "free")),
        )
        items.append(
            NewsItem(
                item_id=stable_item_id(source_id, url, title),
                title=title,
                summary=summary,
                language=str(source.get("language", "en")),
                tags=list(source.get("tags", [])),
                published_at=normalize_published(raw_published),
                published_raw=raw_published,
                sources=[source_ref],
                image_url=_image_from_entry(entry),
            )
        )
    status.update({"ok": bool(items), "count": len(items)})
    return items, status


def fetch_all(sources: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[NewsItem], list[dict[str, Any]]]:
    timeout = float(config.get("timeout_seconds", 20))
    max_workers = int(config.get("max_concurrent", 6))
    verify_tls = bool(config.get("verify_tls", True))
    proxy = str(config.get("proxy", "")).strip()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    items: list[NewsItem] = []
    statuses: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending = {
            executor.submit(fetch_source, src, timeout, verify_tls, proxies): src for src in sources
        }
        for future in as_completed(pending):
            fetched, status = future.result()
            items.extend(fetched)
            statuses.append(status)

    # Concurrency completion order must never affect downstream IDs or AI input.
    unique = {item.item_id: item for item in items}
    ordered = sorted(
        unique.values(),
        key=lambda item: (item.published_at or "", item.sources[0].source_id, item.item_id),
        reverse=True,
    )
    statuses.sort(key=lambda item: item["source_id"])
    logger.info("fetched %s unique items from %s sources", len(ordered), len(sources))
    return ordered, statuses


def is_on_date(item: NewsItem, run_date: str, timezone_name: str) -> bool | None:
    if not item.published_at:
        return None
    instant = datetime.fromisoformat(item.published_at)
    local_date = instant.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    return local_date == run_date
