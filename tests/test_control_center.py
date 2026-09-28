from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import yaml

from newsletter.config import load_config
from newsletter.incremental import _consume_recent_interests, _merge_rankings
from newsletter.models import RankedEvent
from newsletter.webapp import (
    ASSET_ROOT,
    ControlState,
    NewsletterServer,
    _save_settings,
    _settings_payload,
    _validate_settings,
)

ROOT = Path(__file__).resolve().parent.parent


def ranked(event_id: str, score: float) -> RankedEvent:
    return RankedEvent(
        event_id=event_id,
        importance_score=score,
        interest_score=0,
        confidence=0,
        reason="",
    )


class ControlCenterTests(unittest.TestCase):
    def test_settings_accept_new_source_and_expose_score_formula(self) -> None:
        payload = _settings_payload(ROOT / "config")
        payload["sources"].append(
            {
                "id": "rfi",
                "name": "RFI",
                "provider": "google_news",
                "search": "site:rfi.fr",
                "google_hl": "fr",
                "google_gl": "FR",
                "google_ceid": "FR:fr",
                "weight": 0.75,
                "language": "fr",
                "access_type": "free",
                "tags": ["international", "france"],
            }
        )
        result = _validate_settings(payload)
        self.assertEqual(result["sources"][-1]["id"], "rfi")
        self.assertEqual(
            result["ranking"]["score_adjustment"]["corroboration_bonus_4_plus"], 6
        )

    def test_incremental_merge_keeps_forty_and_allows_new_top_story(self) -> None:
        old = [ranked(f"old-{index}", 90 - index if index < 15 else 0) for index in range(40)]
        new = [ranked("new-top", 99), ranked("new-ordinary", 0)]
        merged = _merge_rankings(old, new, 1)
        self.assertEqual(len(merged), 40)
        self.assertEqual(merged[0].event_id, "new-top")
        self.assertIn("new-ordinary", {row.event_id for row in merged})
        self.assertEqual(len({row.event_id for row in merged}), 40)

    def test_static_ui_has_required_controls(self) -> None:
        html = (ASSET_ROOT / "index.html").read_text(encoding="utf-8")
        for required in (
            'id="console"',
            'id="generateButton"',
            'id="historyList"',
            'id="sourceList"',
            'id="saveSettings"',
            'id="timezone"',
            'id="formulaPosition"',
            'id="recentInterests"',
        ):
            self.assertIn(required, html)
        self.assertNotIn("onclick=", html)
        self.assertIn('href="newsletter/ui/app.css"', html)
        self.assertIn('src="newsletter/ui/app.js"', html)
        self.assertIn("运行每日新闻.cmd", html)

        root_entry = ROOT / "每日新闻简报控制中心.html"
        self.assertTrue(root_entry.is_file())
        entry_html = root_entry.read_text(encoding="utf-8")
        self.assertEqual(entry_html, html)

    def test_local_server_serves_status_and_settings(self) -> None:
        state = ControlState(ROOT / "config")
        server = NewsletterServer(("127.0.0.1", 0), state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(base + "/api/status", timeout=3) as response:
                status = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(base + "/api/settings", timeout=3) as response:
                settings = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(base + "/newsletter/ui/app.css", timeout=3) as response:
                stylesheet = response.read().decode("utf-8")
            self.assertEqual(status["state"], "idle")
            self.assertEqual(settings["selection"]["headline_count"], 10)
            self.assertIn("Asia/Shanghai", settings["timezones"])
            self.assertIn(".page-shell", stylesheet)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_archive_html_is_served_with_inline_styles_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            config_dir = project / "config"
            shutil.copytree(ROOT / "config", config_dir)
            archive_file = project / "archive" / "2026-09-29" / "newsletter-20260929-1.html"
            archive_file.parent.mkdir(parents=True)
            archive_file.write_text(
                "<!doctype html><style>body{color:#123}</style><main>archive body</main>",
                encoding="utf-8",
            )
            state = ControlState(config_dir)
            server = NewsletterServer(("127.0.0.1", 0), state)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base + "/api/history", timeout=3) as response:
                    history = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(base + history["items"][0]["url"], timeout=3) as response:
                    body = response.read().decode("utf-8")
                    policy = response.headers["Content-Security-Policy"]
                self.assertIn("archive body", body)
                self.assertIn("style-src 'unsafe-inline'", policy)
                self.assertNotIn("script-src 'unsafe-inline'", policy)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_generate_endpoint_dispatches_one_click_pipeline(self) -> None:
        state = ControlState(ROOT / "config")
        server = NewsletterServer(("127.0.0.1", 0), state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        dispatched = threading.Event()

        def fake_generation(control_state: ControlState, force_full: bool) -> None:
            self.assertFalse(force_full)
            with control_state.lock:
                control_state.state = "success"
            dispatched.set()

        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            request = urllib.request.Request(
                base + "/api/generate",
                data=json.dumps({"force_full": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("newsletter.webapp._run_generation", side_effect=fake_generation):
                with urllib.request.urlopen(request, timeout=3) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 202)
                self.assertTrue(result["ok"])
                self.assertTrue(dispatched.wait(timeout=3))
            self.assertEqual(state.state, "success")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_recent_interest_does_not_invalidate_incremental_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            config_dir = project / "config"
            shutil.copytree(ROOT / "config", config_dir)
            before = load_config(config_dir)
            payload = _settings_payload(config_dir)
            payload["interests"]["recent"] = ["下一次只关注人工智能峰会"]
            result = _save_settings(config_dir, payload)
            after = load_config(config_dir)
            self.assertFalse(result["requires_full_run"])
            self.assertEqual(before.config_hash, after.config_hash)
            self.assertEqual(after.interests["recent"], ["下一次只关注人工智能峰会"])

    def test_recent_interest_is_cleared_only_when_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            config_dir = project / "config"
            shutil.copytree(ROOT / "config", config_dir)
            interests_path = config_dir / "interests.yaml"
            document = yaml.safe_load(interests_path.read_text(encoding="utf-8"))
            document["recent"] = ["一次性主题"]
            interests_path.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            config = load_config(config_dir)
            _consume_recent_interests(config)
            saved = yaml.safe_load(interests_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["recent"], [])


if __name__ == "__main__":
    unittest.main()
