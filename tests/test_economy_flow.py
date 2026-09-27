from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from newsletter.models import EventGroup, NewsItem, SourceRef, Translation
from newsletter.pipeline import _next_edition_number
from newsletter.ranking import build_candidate_pool, rank_events
from newsletter.render import build_newsletter_data, render_html


def make_group(index: int, source_count: int = 1) -> EventGroup:
    sources = [
        SourceRef(
            source_id=f"source-{(index + offset) % 10}",
            name=f"Source {(index + offset) % 10}",
            url=f"https://example.com/{index}/{offset}",
            weight=0.65 + ((index + offset) % 6) * 0.05,
        )
        for offset in range(source_count)
    ]
    item = NewsItem(
        item_id=f"item-{index}",
        title=f"Event {index} election and public policy",
        summary=f"Compact factual summary for event {index}.",
        language="en",
        tags=["source-config-tag"],
        published_at="2026-09-28T00:00:00+00:00",
        published_raw=None,
        sources=sources,
    )
    return EventGroup(
        event_id=f"event-{index}",
        group_type="exact_match" if source_count > 1 else "single",
        leader_item_id=item.item_id,
        items=[item],
    )


class FakeClient:
    def __init__(self) -> None:
        self.event_payload: list[dict[str, object]] = []

    def structured_prompt(self, **kwargs):
        prompt = kwargs["prompt"]
        self.event_payload = json.loads(prompt.split("Events: ", 1)[1])
        ids = [row["event_id"] for row in self.event_payload]
        return {
            "top15": [
                {"event_id": event_id, "importance_score": 90 - index}
                for index, event_id in enumerate(ids[:15])
            ],
            "ordinary25": ids[15:40],
        }


class EconomyFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.groups = [make_group(index, 2 if index < 7 else 1) for index in range(100)]
        self.interests = {"long_term": ["AI", "地缘政治"], "recent": []}
        self.config = {
            "candidate_pool_size": 60,
            "min_candidates_per_source": 3,
            "max_candidates_per_source": 8,
            "interest_candidate_slots": 5,
            "wildcard_slots": 5,
            "top_scored_count": 15,
            "ordinary_selected_count": 25,
            "models": ["free-test-model"],
        }

    def test_candidate_pool_and_minimal_ai_contract(self) -> None:
        candidates, audit = build_candidate_pool(self.groups, self.interests, self.config)
        self.assertEqual(len(candidates), 60)
        self.assertEqual(audit["candidate_pool_size"], 60)

        client = FakeClient()
        ranked, result_audit = rank_events(
            self.groups, self.interests, self.config, client  # type: ignore[arg-type]
        )
        self.assertEqual(len(ranked), 40)
        self.assertEqual(len(result_audit["top15_adjusted_order"]), 15)
        self.assertTrue(all(row.importance_score > 0 for row in ranked[:15]))
        self.assertTrue(all(row.importance_score == 0 for row in ranked[15:]))
        self.assertEqual(
            set(client.event_payload[0]), {"event_id", "title", "summary"}
        )
        self.assertNotIn("source-config-tag", json.dumps(client.event_payload))

    def test_render_is_ten_plus_thirty(self) -> None:
        client = FakeClient()
        ranked, _ = rank_events(
            self.groups, self.interests, self.config, client  # type: ignore[arg-type]
        )
        selected = {row.event_id for row in ranked}
        groups = [group for group in self.groups if group.event_id in selected]
        translations = [
            Translation(
                item_id=group.leader_item_id,
                title_zh=f"新闻 {group.event_id}",
                summary_zh="摘要",
                title_provider="google_gtx",
                summary_provider="google_gtx",
            )
            for group in groups
        ]
        newsletter = build_newsletter_data(
            run_date="2026-09-28",
            groups=groups,
            rankings=ranked,
            translations=translations,
            headline_count=10,
            ordinary_count=30,
            backup_count=0,
            stats={},
        )
        self.assertEqual(len(newsletter["headlines"]), 10)
        self.assertEqual(len(newsletter["ordinary"]), 30)
        self.assertEqual(newsletter["backup"], [])
        self.assertNotIn("编辑理由", render_html(newsletter))

    def test_daily_edition_number_never_reuses_an_existing_name(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            archive = Path(value)
            (archive / "newsletter-20260928-1.html").touch()
            (archive / "newsletter-20260928-2.json").touch()
            (archive / "newsletter-other.html").touch()
            self.assertEqual(_next_edition_number(archive, "20260928"), 3)


if __name__ == "__main__":
    unittest.main()
