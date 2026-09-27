from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .config import AppConfig
from .dedup import group_events
from .errors import StageError
from .fetch import fetch_all
from .filtering import filter_items
from .models import EventGroup, NewsItem, RankedEvent, Translation
from .opencode_client import client_from_config
from .ranking import rank_events
from .render import build_newsletter_data, render_html, render_markdown
from .storage import RunContext, atomic_write_json, atomic_write_text, read_json, utc_now
from .translation import translate_selected

logger = logging.getLogger(__name__)


def _items_from(path: Path, key: str = "items") -> list[NewsItem]:
    return [NewsItem.from_dict(row) for row in read_json(path)[key]]


def _groups_from(path: Path) -> list[EventGroup]:
    return [EventGroup.from_dict(row) for row in read_json(path)["events"]]


def _rankings_from(path: Path) -> list[RankedEvent]:
    return [RankedEvent.from_dict(row) for row in read_json(path)["ranked"]]


def _translations_from(path: Path) -> list[Translation]:
    return [Translation.from_dict(row) for row in read_json(path)["translations"]]


def _next_edition_number(archive_dir: Path, compact_date: str) -> int:
    pattern = re.compile(rf"^newsletter-{re.escape(compact_date)}-(\d+)\.(?:json|md|html)$")
    numbers = []
    for path in archive_dir.glob(f"newsletter-{compact_date}-*.*"):
        match = pattern.fullmatch(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _publish(context: RunContext, config: AppConfig) -> dict[str, str]:
    archive_dir = config.paths["archive"] / context.run_date
    latest_dir = config.paths["latest"]
    archive_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    compact_date = context.run_date.replace("-", "")
    edition_number = _next_edition_number(archive_dir, compact_date)
    edition_name = f"newsletter-{compact_date}-{edition_number}"

    published: dict[str, str] = {}
    for source_name, suffix in (
        ("06_newsletter.json", "json"),
        ("newsletter.md", "md"),
        ("newsletter.html", "html"),
    ):
        content = (context.run_dir / source_name).read_text(encoding="utf-8")
        # Every completed run is immutable and gets a human-readable daily sequence.
        archive_path = archive_dir / f"{edition_name}.{suffix}"
        latest_path = latest_dir / f"{edition_name}.{suffix}"
        if archive_path.exists() or latest_path.exists():
            raise StageError("publish", f"refusing to overwrite edition: {edition_name}.{suffix}")
        atomic_write_text(archive_path, content)
        atomic_write_text(latest_path, content)
        published[suffix] = str(archive_path)

    # This pointer is written last and is the commit record for the latest edition.
    pointer = {
        "schema_version": 1,
        "run_id": context.run_id,
        "run_date": context.run_date,
        "edition_number": edition_number,
        "edition_name": edition_name,
        "published_at": utc_now(),
        "files": {
            suffix: f"{edition_name}.{suffix}" for suffix in ("json", "md", "html")
        },
    }
    atomic_write_json(latest_dir / "current.json", pointer)
    return published


def run_pipeline(context: RunContext, config: AppConfig) -> dict[str, Any]:
    pipeline = config.pipeline
    client = client_from_config(dict(pipeline.get("opencode") or {}), config.root)
    stage = "fetch"
    stats: dict[str, Any] = {}
    try:
        artifact = "01_raw.json"
        if context.stage_completed(stage, artifact):
            raw = read_json(context.run_dir / artifact)
            items = [NewsItem.from_dict(row) for row in raw["items"]]
            source_status = list(raw.get("source_status", []))
        else:
            context.begin_stage(stage)
            items, source_status = fetch_all(config.sources, dict(pipeline.get("fetch") or {}))
            if not items:
                raise StageError(stage, "all sources returned zero news items")
            atomic_write_json(
                context.run_dir / artifact,
                {"items": [item.to_dict() for item in items], "source_status": source_status},
            )
            context.complete_stage(stage, artifact, item_count=len(items))
        stats["fetch"] = {"items": len(items), "sources": source_status}

        stage = "filter"
        artifact = "02_filtered.json"
        if context.stage_completed(stage, artifact):
            filtered_doc = read_json(context.run_dir / artifact)
            filtered = [NewsItem.from_dict(row) for row in filtered_doc["items"]]
            filter_stats = dict(filtered_doc.get("stats", {}))
        else:
            context.begin_stage(stage)
            filtered, filter_stats = filter_items(
                items,
                context.run_date,
                config.timezone,
                dict(pipeline.get("filtering") or {}),
                str(context.manifest.get("created_at") or "") or None,
            )
            if not filtered:
                raise StageError(stage, "no items match the requested date and filters")
            atomic_write_json(
                context.run_dir / artifact,
                {"items": [item.to_dict() for item in filtered], "stats": filter_stats},
            )
            context.complete_stage(stage, artifact, item_count=len(filtered))
        stats["filter"] = filter_stats

        stage = "deduplicate"
        artifact = "03_events.json"
        if context.stage_completed(stage, artifact):
            event_doc = read_json(context.run_dir / artifact)
            groups = [EventGroup.from_dict(row) for row in event_doc["events"]]
            dedup_stats = dict(event_doc.get("stats", {}))
        else:
            context.begin_stage(stage)
            dedup_config = dict(pipeline.get("deduplication") or {})
            groups, dedup_stats = group_events(
                filtered,
                exact_threshold=float(dedup_config.get("exact_threshold", 0.72)),
                related_threshold=float(dedup_config.get("related_threshold", 0.34)),
            )
            atomic_write_json(
                context.run_dir / artifact,
                {"events": [group.to_dict() for group in groups], "stats": dedup_stats},
            )
            context.complete_stage(stage, artifact, event_count=len(groups))
        stats["deduplicate"] = dedup_stats

        stage = "rank"
        artifact = "04_ranking.json"
        if context.stage_completed(stage, artifact):
            ranking_doc = read_json(context.run_dir / artifact)
            rankings = [RankedEvent.from_dict(row) for row in ranking_doc["ranked"]]
            candidate_audit = dict(ranking_doc.get("candidate_audit", {}))
        else:
            context.begin_stage(stage)
            rankings, candidate_audit = rank_events(
                groups,
                config.interests,
                dict(pipeline.get("ranking") or {}),
                client,
            )
            atomic_write_json(
                context.run_dir / artifact,
                {
                    "ranked": [ranking.to_dict() for ranking in rankings],
                    "candidate_audit": candidate_audit,
                },
            )
            atomic_write_json(context.run_dir / "candidate_audit.json", candidate_audit)
            context.complete_stage(stage, artifact, ranked_count=len(rankings))

        selection = dict(pipeline.get("selection") or {})
        headline_count = max(0, int(selection.get("headline_count", 10)))
        ordinary_count = max(0, int(selection.get("ordinary_count", 30)))
        backup_count = max(0, int(selection.get("backup_count", 0)))
        requested_count = headline_count + ordinary_count + backup_count
        rankings = rankings[:requested_count]
        selected_ids = {row.event_id for row in rankings}
        selected_groups = [group for group in groups if group.event_id in selected_ids]
        headline_event_ids = [row.event_id for row in rankings[:headline_count]]
        stats["selection"] = {
            "candidate_pool_count": int(candidate_audit.get("candidate_pool_size", 0)),
            "ai_top_scored_count": min(15, len(rankings)),
            "selected_count": len(rankings),
            "headline_count": headline_count,
            "ordinary_count": ordinary_count,
            "backup_count": backup_count,
        }

        stage = "translate"
        artifact = "05_translation.json"
        if context.stage_completed(stage, artifact):
            translations = _translations_from(context.run_dir / artifact)
        else:
            context.begin_stage(stage)
            translations = translate_selected(
                selected_groups,
                dict(pipeline.get("translation") or {}),
                client,
                config.terminology,
                headline_event_ids=headline_event_ids,
            )

            # A title is mandatory. If even the conditional AI rescue failed, remove
            # that event and promote a deterministic reserve candidate using GTX only.
            translated_by_id = {row.item_id: row for row in translations}
            groups_by_id = {group.event_id: group for group in groups}
            failed_event_ids = {
                group.event_id
                for group in selected_groups
                if not translated_by_id.get(group.leader_item_id)
                or not translated_by_id[group.leader_item_id].title_zh.strip()
            }
            replacements: list[dict[str, str]] = []
            if failed_event_ids:
                rankings = [row for row in rankings if row.event_id not in failed_event_ids]
                reserve_ids = list(candidate_audit.get("reserve_ids") or [])
                gtx_only = dict(pipeline.get("translation") or {})
                gtx_only["providers"] = ["google_gtx"]
                for reserve_id in reserve_ids:
                    if len(rankings) >= requested_count:
                        break
                    group = groups_by_id.get(reserve_id)
                    if group is None:
                        continue
                    reserve_translations = translate_selected(
                        [group], gtx_only, client, headline_event_ids=[]
                    )
                    reserve_by_id = {row.item_id: row for row in reserve_translations}
                    leader = reserve_by_id.get(group.leader_item_id)
                    if leader is None or not leader.title_zh.strip():
                        continue
                    translations.extend(reserve_translations)
                    rankings.append(
                        RankedEvent(
                            event_id=reserve_id,
                            importance_score=0,
                            interest_score=0,
                            confidence=0,
                            reason="",
                            rule_score=0,
                        )
                    )
                    replacements.append(
                        {"removed": sorted(failed_event_ids)[0], "promoted": reserve_id}
                    )
                selected_ids = {row.event_id for row in rankings}
                selected_groups = [group for group in groups if group.event_id in selected_ids]
                candidate_audit["translation_failed_event_ids"] = sorted(failed_event_ids)
                candidate_audit["translation_replacements"] = replacements
                atomic_write_json(
                    context.run_dir / "04_ranking.json",
                    {
                        "ranked": [ranking.to_dict() for ranking in rankings],
                        "candidate_audit": candidate_audit,
                    },
                )
                atomic_write_json(context.run_dir / "candidate_audit.json", candidate_audit)
            atomic_write_json(
                context.run_dir / artifact,
                {"translations": [translation.to_dict() for translation in translations]},
            )
            context.complete_stage(stage, artifact, translated_count=len(translations))

        stats["selection"]["final_selected_count"] = len(rankings)

        stats["ai_usage"] = client.usage_summary()
        atomic_write_json(context.run_dir / "ai_usage.json", stats["ai_usage"])

        stage = "render"
        artifact = "06_newsletter.json"
        if context.stage_completed(stage, artifact):
            newsletter = read_json(context.run_dir / artifact)
        else:
            context.begin_stage(stage)
            newsletter = build_newsletter_data(
                run_date=context.run_date,
                groups=selected_groups,
                rankings=rankings,
                translations=translations,
                headline_count=headline_count,
                ordinary_count=ordinary_count,
                backup_count=backup_count,
                stats=stats,
            )
            atomic_write_json(context.run_dir / artifact, newsletter)
            atomic_write_text(context.run_dir / "newsletter.md", render_markdown(newsletter))
            atomic_write_text(context.run_dir / "newsletter.html", render_html(newsletter))
            context.complete_stage(
                stage,
                artifact,
                headline_count=len(newsletter["headlines"]),
                ordinary_count=len(newsletter["ordinary"]),
            )

        stage = "publish"
        artifact = "published.json"
        if context.stage_completed(stage, artifact):
            published = read_json(context.run_dir / artifact)
        else:
            context.begin_stage(stage)
            published = _publish(context, config)
            atomic_write_json(context.run_dir / artifact, published)
            context.complete_stage(stage, artifact, **published)

        context.finish()
        logger.info("run %s completed", context.run_id)
        return {"run_id": context.run_id, "run_dir": str(context.run_dir), "published": published}
    except Exception as exc:
        context.fail(stage, str(exc))
        raise
