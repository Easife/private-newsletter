from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .config import AppConfig
from .dedup import group_events
from .errors import StageError
from .fetch import fetch_all
from .filtering import filter_items
from .models import EventGroup, NewsItem, RankedEvent, Translation
from .opencode_client import client_from_config
from .pipeline import _publish, run_pipeline
from .ranking import rank_events
from .render import build_newsletter_data, render_html, render_markdown
from .storage import (
    RunContext,
    application_fingerprint,
    atomic_write_json,
    atomic_write_text,
    read_json,
)
from .translation import translate_selected

logger = logging.getLogger(__name__)

REQUIRED_BASELINE_ARTIFACTS = (
    "01_raw.json",
    "03_events.json",
    "04_ranking.json",
    "05_translation.json",
    "06_newsletter.json",
)


def find_incremental_baseline(config: AppConfig, run_date: str) -> Path | None:
    date_dir = config.paths["runs"] / run_date
    if not date_dir.is_dir():
        return None
    fingerprint = application_fingerprint()
    for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = read_json(manifest_path)
        except Exception:
            continue
        if (
            manifest.get("status") != "complete"
            or manifest.get("run_date") != run_date
            or manifest.get("config_hash") != config.config_hash
            or manifest.get("app_version") != __version__
            or manifest.get("app_fingerprint") != fingerprint
        ):
            continue
        if all((run_dir / name).is_file() for name in REQUIRED_BASELINE_ARTIFACTS):
            return run_dir
    return None


def generation_mode(config: AppConfig, run_date: str) -> dict[str, Any]:
    baseline = find_incremental_baseline(config, run_date)
    if baseline is None:
        return {
            "mode": "full",
            "label": "今日首次完整运行",
            "reason": "今天没有与当前代码和设置完全匹配的成功简报。",
            "baseline_run_id": None,
        }
    return {
        "mode": "incremental",
        "label": "今日增量运行",
        "reason": "只评估和翻译上次成功抓取后出现的全新事件。",
        "baseline_run_id": baseline.name,
    }


def _events_from(path: Path) -> list[EventGroup]:
    return [EventGroup.from_dict(row) for row in read_json(path)["events"]]


def _rankings_from(path: Path) -> list[RankedEvent]:
    return [RankedEvent.from_dict(row) for row in read_json(path)["ranked"]]


def _translations_from(path: Path) -> list[Translation]:
    return [Translation.from_dict(row) for row in read_json(path)["translations"]]


def _merge_rankings(
    old_rankings: list[RankedEvent],
    new_rankings: list[RankedEvent],
    new_top_count: int,
    *,
    scored_count: int = 15,
    total_count: int = 40,
) -> list[RankedEvent]:
    old_top = old_rankings[:scored_count]
    new_top = new_rankings[:new_top_count]
    combined_top = sorted(
        old_top + new_top,
        key=lambda row: (row.final_score, row.event_id),
        reverse=True,
    )
    final_top = combined_top[:scored_count]
    seen = {row.event_id for row in final_top}
    tail_candidates = combined_top[scored_count:] + new_rankings[new_top_count:] + old_rankings[scored_count:]
    final_tail: list[RankedEvent] = []
    for row in tail_candidates:
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        final_tail.append(row)
        if len(final_top) + len(final_tail) >= total_count:
            break
    return final_top + final_tail


def run_auto_pipeline(
    context: RunContext,
    config: AppConfig,
    *,
    force_full: bool = False,
) -> dict[str, Any]:
    baseline = None if force_full else find_incremental_baseline(config, context.run_date)
    if baseline is None:
        logger.info("generation mode: full")
        result = run_pipeline(context, config)
    else:
        logger.info("generation mode: incremental; baseline=%s", baseline.name)
        result = run_incremental_pipeline(context, config, baseline)
    _consume_recent_interests(config)
    return result


def _consume_recent_interests(config: AppConfig) -> None:
    if not config.interests.get("recent"):
        return
    path = config.config_dir / "interests.yaml"
    if not path.is_file():
        return
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        return
    document["recent"] = []
    atomic_write_text(path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
    logger.info("one-shot interests consumed and cleared after successful generation")


def run_incremental_pipeline(
    context: RunContext,
    config: AppConfig,
    baseline_dir: Path,
) -> dict[str, Any]:
    pipeline = config.pipeline
    stage = "fetch"
    stats: dict[str, Any] = {}
    try:
        context.begin_stage(stage)
        items, source_status = fetch_all(config.sources, dict(pipeline.get("fetch") or {}))
        if not items:
            raise StageError(stage, "all sources returned zero news items")
        atomic_write_json(
            context.run_dir / "01_raw.json",
            {"items": [item.to_dict() for item in items], "source_status": source_status},
        )
        context.complete_stage(stage, "01_raw.json", item_count=len(items))
        stats["fetch"] = {"items": len(items), "sources": source_status}

        stage = "filter"
        context.begin_stage(stage)
        filtered, filter_stats = filter_items(
            items,
            context.run_date,
            config.timezone,
            dict(pipeline.get("filtering") or {}),
            str(context.manifest.get("created_at") or "") or None,
        )
        if not filtered:
            raise StageError(stage, "no items match the rolling window and filters")
        atomic_write_json(
            context.run_dir / "02_filtered.json",
            {"items": [item.to_dict() for item in filtered], "stats": filter_stats},
        )
        context.complete_stage(stage, "02_filtered.json", item_count=len(filtered))
        stats["filter"] = filter_stats

        stage = "deduplicate"
        context.begin_stage(stage)
        dedup_config = dict(pipeline.get("deduplication") or {})
        current_groups, dedup_stats = group_events(
            filtered,
            exact_threshold=float(dedup_config.get("exact_threshold", 0.72)),
            related_threshold=float(dedup_config.get("related_threshold", 0.34)),
        )
        previous_raw_ids = {
            row["item_id"] for row in read_json(baseline_dir / "01_raw.json")["items"]
        }
        new_groups = [
            group
            for group in current_groups
            if all(item.item_id not in previous_raw_ids for item in group.items)
        ]

        old_groups = _events_from(baseline_dir / "03_events.json")
        old_rankings = _rankings_from(baseline_dir / "04_ranking.json")
        old_translations = _translations_from(baseline_dir / "05_translation.json")
        old_selected_ids = {row.event_id for row in old_rankings}
        carried_groups = [group for group in old_groups if group.event_id in old_selected_ids]
        event_map = {group.event_id: group for group in current_groups}
        for group in carried_groups:
            event_map.setdefault(group.event_id, group)
        combined_events = list(event_map.values())
        atomic_write_json(
            context.run_dir / "03_events.json",
            {
                "events": [group.to_dict() for group in combined_events],
                "stats": dedup_stats,
                "incremental": {
                    "baseline_run_id": baseline_dir.name,
                    "new_event_count": len(new_groups),
                    "new_event_ids": [group.event_id for group in new_groups],
                },
            },
        )
        context.complete_stage(
            stage,
            "03_events.json",
            event_count=len(current_groups),
            new_event_count=len(new_groups),
        )
        stats["deduplicate"] = dedup_stats

        stage = "rank"
        context.begin_stage(stage)
        client = client_from_config(dict(pipeline.get("opencode") or {}), config.root)
        ranking_config = dict(pipeline.get("ranking") or {})
        configured_top = int(ranking_config.get("top_scored_count", 15))
        new_rankings: list[RankedEvent] = []
        candidate_audit: dict[str, Any] = {
            "candidate_pool_size": 0,
            "candidate_ids": [],
            "reserve_ids": [],
        }
        new_top_count = 0
        if new_groups:
            max_selected = min(40, len(new_groups))
            new_top_count = min(configured_top, max_selected)
            ranking_config["candidate_pool_size"] = min(
                int(ranking_config.get("candidate_pool_size", 60)), len(new_groups)
            )
            ranking_config["top_scored_count"] = new_top_count
            ranking_config["ordinary_selected_count"] = max_selected - new_top_count
            new_rankings, candidate_audit = rank_events(
                new_groups, config.interests, ranking_config, client
            )

        selection = dict(pipeline.get("selection") or {})
        headline_count = max(0, int(selection.get("headline_count", 10)))
        ordinary_count = max(0, int(selection.get("ordinary_count", 30)))
        backup_count = max(0, int(selection.get("backup_count", 0)))
        total_count = headline_count + ordinary_count + backup_count
        scored_count = min(configured_top, total_count)
        final_rankings = _merge_rankings(
            old_rankings,
            new_rankings,
            new_top_count,
            scored_count=scored_count,
            total_count=total_count,
        )
        candidate_audit.update(
            {
                "incremental": True,
                "baseline_run_id": baseline_dir.name,
                "new_event_count": len(new_groups),
                "new_ranked_count": len(new_rankings),
                "merged_order": [row.event_id for row in final_rankings],
            }
        )
        atomic_write_json(
            context.run_dir / "04_ranking.json",
            {
                "ranked": [row.to_dict() for row in final_rankings],
                "candidate_audit": candidate_audit,
            },
        )
        atomic_write_json(context.run_dir / "candidate_audit.json", candidate_audit)
        context.complete_stage(
            stage,
            "04_ranking.json",
            ranked_count=len(final_rankings),
            new_ranked_count=len(new_rankings),
        )

        stage = "translate"
        context.begin_stage(stage)
        group_by_id = {group.event_id: group for group in combined_events}
        final_ids = {row.event_id for row in final_rankings}
        selected_groups = [group_by_id[event_id] for event_id in final_ids if event_id in group_by_id]
        new_ids = {group.event_id for group in new_groups}
        new_selected_groups = [group for group in selected_groups if group.event_id in new_ids]
        new_translations: list[Translation] = []
        if new_selected_groups:
            new_translations = translate_selected(
                new_selected_groups,
                dict(pipeline.get("translation") or {}),
                client,
                config.terminology,
                headline_event_ids=[
                    row.event_id
                    for row in final_rankings[:headline_count]
                    if row.event_id in new_ids
                ],
            )
            translated_new = {row.item_id: row for row in new_translations}
            failed_new_ids = {
                group.event_id
                for group in new_selected_groups
                if not translated_new.get(group.leader_item_id)
                or not translated_new[group.leader_item_id].title_zh.strip()
            }
            if failed_new_ids:
                new_rankings = [
                    row for row in new_rankings if row.event_id not in failed_new_ids
                ]
                final_rankings = _merge_rankings(
                    old_rankings,
                    new_rankings,
                    min(new_top_count, len(new_rankings)),
                    scored_count=scored_count,
                    total_count=total_count,
                )
                final_ids = {row.event_id for row in final_rankings}
                selected_groups = [
                    group_by_id[event_id] for event_id in final_ids if event_id in group_by_id
                ]
                candidate_audit["translation_failed_event_ids"] = sorted(failed_new_ids)
                atomic_write_json(
                    context.run_dir / "04_ranking.json",
                    {
                        "ranked": [row.to_dict() for row in final_rankings],
                        "candidate_audit": candidate_audit,
                    },
                )

        translation_map = {row.item_id: row for row in old_translations}
        translation_map.update({row.item_id: row for row in new_translations})
        needed_item_ids = {item.item_id for group in selected_groups for item in group.items}
        final_translations = [
            translation_map[item_id]
            for item_id in sorted(needed_item_ids)
            if item_id in translation_map
        ]
        missing_leaders = [
            group.leader_item_id
            for group in selected_groups
            if group.leader_item_id not in translation_map
        ]
        if missing_leaders:
            raise StageError(
                stage, f"missing translations for {len(missing_leaders)} selected leaders"
            )
        atomic_write_json(
            context.run_dir / "05_translation.json",
            {"translations": [row.to_dict() for row in final_translations]},
        )
        context.complete_stage(
            stage,
            "05_translation.json",
            translated_count=len(final_translations),
            newly_translated_count=len(new_translations),
        )

        stats["selection"] = {
            "mode": "incremental",
            "baseline_run_id": baseline_dir.name,
            "new_event_count": len(new_groups),
            "new_ranked_count": len(new_rankings),
            "newly_translated_count": len(new_translations),
            "final_selected_count": len(final_rankings),
            "headline_count": headline_count,
            "ordinary_count": ordinary_count,
            "backup_count": backup_count,
        }
        stats["ai_usage"] = client.usage_summary()
        atomic_write_json(context.run_dir / "ai_usage.json", stats["ai_usage"])

        stage = "render"
        context.begin_stage(stage)
        newsletter = build_newsletter_data(
            run_date=context.run_date,
            groups=selected_groups,
            rankings=final_rankings,
            translations=final_translations,
            headline_count=headline_count,
            ordinary_count=ordinary_count,
            backup_count=backup_count,
            stats=stats,
        )
        atomic_write_json(context.run_dir / "06_newsletter.json", newsletter)
        atomic_write_text(context.run_dir / "newsletter.md", render_markdown(newsletter))
        atomic_write_text(context.run_dir / "newsletter.html", render_html(newsletter))
        context.complete_stage(
            stage,
            "06_newsletter.json",
            headline_count=len(newsletter["headlines"]),
            ordinary_count=len(newsletter["ordinary"]),
        )

        stage = "publish"
        context.begin_stage(stage)
        published = _publish(context, config)
        atomic_write_json(context.run_dir / "published.json", published)
        context.complete_stage(stage, "published.json", **published)
        context.finish()
        logger.info("incremental run %s completed", context.run_id)
        return {
            "run_id": context.run_id,
            "run_dir": str(context.run_dir),
            "mode": "incremental",
            "baseline_run_id": baseline_dir.name,
            "new_event_count": len(new_groups),
            "published": published,
        }
    except Exception as exc:
        context.fail(stage, str(exc))
        raise
