from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def event_sources(event: dict[str, Any]) -> set[str]:
    return {
        source["source_id"]
        for item in event["items"]
        for source in item.get("sources", [])
    }


def source_counts(events: list[dict[str, Any]], ids: set[str] | None = None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        if ids is None or event["event_id"] in ids:
            counts.update(event_sources(event))
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()

    raw = load(run_dir / "01_raw.json")
    filtered = load(run_dir / "02_filtered.json")
    event_doc = load(run_dir / "03_events.json")
    ranking = load(run_dir / "04_ranking.json")
    translations = load(run_dir / "05_translation.json")
    newsletter = load(run_dir / "06_newsletter.json")
    usage = load(run_dir / "ai_usage.json")
    manifest = load(run_dir / "manifest.json")

    events = event_doc["events"]
    candidate_ids = set(ranking["candidate_audit"]["candidate_ids"])
    selected_ids = {row["event_id"] for row in ranking["ranked"]}
    headline_ids = {row["event_id"] for row in newsletter["headlines"]}
    ordinary_ids = {row["event_id"] for row in newsletter["ordinary"]}

    raw_counts = Counter(
        source["source_id"] for item in raw["items"] for source in item.get("sources", [])
    )
    filtered_counts = Counter(
        source["source_id"]
        for item in filtered["items"]
        for source in item.get("sources", [])
    )
    title_providers = Counter(row["title_provider"] for row in translations["translations"])
    summary_providers = Counter(row["summary_provider"] for row in translations["translations"])
    language_counts = Counter(item["language"] for item in filtered["items"])
    timestamps = [
        datetime.fromisoformat(item["published_at"])
        for item in filtered["items"]
        if item.get("published_at")
    ]
    all_final_ids = list(headline_ids | ordinary_ids)
    source_status = Counter(
        "ok" if row.get("ok") is True else "failed"
        for row in raw.get("source_status", [])
    )
    leader_languages = {
        event["event_id"]: next(
            item["language"]
            for item in event["items"]
            if item["item_id"] == event["leader_item_id"]
        )
        for event in events
    }
    translation_errors = [
        row for row in translations["translations"] if row.get("errors")
    ]
    duplicate_ids = headline_ids & ordinary_ids

    stages = manifest["stages"]
    starts = {"fetch": manifest["created_at"]}
    for name in ("filter", "deduplicate", "rank", "translate", "render", "publish"):
        starts[name] = stages[name].get("started_at") or stages[name].get("completed_at")
    durations: dict[str, float] = {}
    prior = datetime.fromisoformat(manifest["created_at"])
    for name in ("fetch", "filter", "deduplicate", "rank", "translate", "render", "publish"):
        completed = datetime.fromisoformat(stages[name]["completed_at"])
        durations[name] = round((completed - prior).total_seconds(), 3)
        prior = completed

    output = {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "counts": {
            "raw_items": len(raw["items"]),
            "filtered_items": len(filtered["items"]),
            "events": len(events),
            "candidate_events": len(candidate_ids),
            "selected_events": len(selected_ids),
            "headlines": len(newsletter["headlines"]),
            "ordinary": len(newsletter["ordinary"]),
            "backup": len(newsletter["backup"]),
        },
        "filter_stats": filtered.get("stats", {}),
        "filtered_time_range": {
            "window_end": manifest["created_at"],
            "window_hours": 24,
            "earliest": min(timestamps).isoformat() if timestamps else None,
            "latest": max(timestamps).isoformat() if timestamps else None,
        },
        "dedup_stats": event_doc.get("stats", {}),
        "source_fetch_status": dict(source_status),
        "source_counts": {
            "raw_items": dict(sorted(raw_counts.items())),
            "filtered_items": dict(sorted(filtered_counts.items())),
            "all_events": source_counts(events),
            "candidates": source_counts(events, candidate_ids),
            "selected": source_counts(events, selected_ids),
            "headlines": source_counts(events, headline_ids),
            "ordinary": source_counts(events, ordinary_ids),
        },
        "filtered_languages": dict(sorted(language_counts.items())),
        "selected_leader_languages": dict(
            Counter(leader_languages[event_id] for event_id in selected_ids)
        ),
        "headline_leader_languages": dict(
            Counter(leader_languages[event_id] for event_id in headline_ids)
        ),
        "translation": {
            "records": len(translations["translations"]),
            "title_providers": dict(title_providers),
            "summary_providers": dict(summary_providers),
            "records_with_errors": len(translation_errors),
            "failed_or_replaced_events": ranking["candidate_audit"].get(
                "translation_failed_event_ids", []
            ),
        },
        "ai_usage": usage,
        "duration_seconds": durations,
        "total_duration_seconds": round(
            (
                datetime.fromisoformat(manifest["completed_at"])
                - datetime.fromisoformat(manifest["created_at"])
            ).total_seconds(),
            3,
        ),
        "integrity": {
            "unique_final_events": len(all_final_ids),
            "headline_ordinary_overlap": sorted(duplicate_ids),
            "all_selected_rendered": selected_ids == headline_ids | ordinary_ids,
            "all_sources_succeeded": set(source_status) == {"ok"},
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
