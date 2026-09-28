from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import re
import shutil
import sys
import threading
import traceback
import webbrowser
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, available_timezones

import yaml

from . import __version__
from .config import AppConfig, load_config
from .errors import NewsletterError
from .incremental import generation_mode, run_auto_pipeline
from .opencode_client import client_from_config
from .storage import RunContext, RunLock, atomic_write_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = Path(__file__).resolve().parent / "ui"
ROOT_INDEX = PROJECT_ROOT / "每日新闻简报控制中心.html"
logger = logging.getLogger(__name__)


class ControlState:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.lock = threading.RLock()
        self.state = "idle"
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.sequence = 0
        self.logs: deque[dict[str, Any]] = deque(maxlen=1200)
        self.environment: dict[str, Any] = {
            "checking": True,
            "python": {"ok": True, "detail": sys.version.split()[0]},
            "virtualenv": {
                "ok": sys.prefix != sys.base_prefix,
                "detail": sys.prefix,
            },
            "config": {"ok": False, "detail": "等待检测"},
            "opencode": {"ok": False, "detail": "等待检测"},
        }

    def add_log(self, level: str, message: str) -> None:
        with self.lock:
            self.sequence += 1
            self.logs.append(
                {
                    "seq": self.sequence,
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "level": level.lower(),
                    "message": message,
                }
            )

    def snapshot(self, after: int = 0) -> dict[str, Any]:
        with self.lock:
            try:
                config = load_config(self.config_dir)
                now = datetime.now(ZoneInfo(config.timezone))
                mode = generation_mode(config, now.date().isoformat())
            except Exception as exc:
                mode = {
                    "mode": "unavailable",
                    "label": "设置需要修正",
                    "reason": str(exc),
                    "baseline_run_id": None,
                }
            return {
                "app_version": __version__,
                "state": self.state,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "last_result": self.last_result,
                "last_error": self.last_error,
                "environment": self.environment,
                "generation_mode": mode,
                "latest_sequence": self.sequence,
                "logs": [row for row in self.logs if row["seq"] > after],
            }


class UiLogHandler(logging.Handler):
    def __init__(self, state: ControlState):
        super().__init__(logging.INFO)
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.state.add_log(record.levelname, self.format(record))
        except Exception:
            pass


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 顶层必须是对象")
    return value


def _settings_payload(config_dir: Path) -> dict[str, Any]:
    pipeline = _read_yaml(config_dir / "pipeline.yaml")
    sources = _read_yaml(config_dir / "sources.yaml").get("sources", [])
    interests = _read_yaml(config_dir / "interests.yaml")
    return {
        "timezone": pipeline.get("timezone", "Asia/Shanghai"),
        "timezones": sorted(available_timezones()),
        "fetch": dict(pipeline.get("fetch") or {}),
        "filtering": dict(pipeline.get("filtering") or {}),
        "deduplication": dict(pipeline.get("deduplication") or {}),
        "selection": dict(pipeline.get("selection") or {}),
        "ranking": {
            key: value
            for key, value in dict(pipeline.get("ranking") or {}).items()
            if key != "models"
        },
        "sources": sources,
        "interests": {
            "long_term": list(interests.get("long_term") or []),
            "recent": list(interests.get("recent") or []),
        },
    }


def _number(value: Any, label: str, low: float, high: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} 必须是数字")
    number = float(value)
    if not low <= number <= high:
        raise ValueError(f"{label} 必须在 {low}–{high} 之间")
    return number


def _integer(value: Any, label: str, low: int, high: int) -> int:
    number = _number(value, label, low, high)
    if int(number) != number:
        raise ValueError(f"{label} 必须是整数")
    return int(number)


def _validate_settings(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("设置必须是 JSON 对象")
    timezone = str(payload.get("timezone", "")).strip()
    if not timezone:
        raise ValueError("时区不能为空")
    ZoneInfo(timezone)

    fetch = dict(payload.get("fetch") or {})
    filtering = dict(payload.get("filtering") or {})
    dedup = dict(payload.get("deduplication") or {})
    selection = dict(payload.get("selection") or {})
    ranking = dict(payload.get("ranking") or {})
    adjustment = dict(ranking.get("score_adjustment") or {})

    fetch["timeout_seconds"] = _integer(fetch.get("timeout_seconds"), "抓取超时", 3, 120)
    fetch["max_concurrent"] = _integer(fetch.get("max_concurrent"), "抓取并发", 1, 32)
    fetch["proxy"] = str(fetch.get("proxy") or "").strip()
    fetch["verify_tls"] = bool(fetch.get("verify_tls", True))
    filtering["window_hours"] = _integer(filtering.get("window_hours"), "时间窗口", 1, 72)
    filtering["min_title_length"] = _integer(
        filtering.get("min_title_length"), "最短标题", 1, 200
    )
    filtering["keep_undated"] = bool(filtering.get("keep_undated", False))
    dedup["exact_threshold"] = _number(
        dedup.get("exact_threshold"), "精确合并阈值", 0.0, 1.0
    )
    dedup["related_threshold"] = _number(
        dedup.get("related_threshold"), "相关报道阈值", 0.0, 1.0
    )
    if dedup["related_threshold"] > dedup["exact_threshold"]:
        raise ValueError("相关报道阈值不能高于精确合并阈值")

    selection["headline_count"] = _integer(selection.get("headline_count"), "头条数量", 1, 30)
    selection["ordinary_count"] = _integer(selection.get("ordinary_count"), "普通新闻数量", 0, 100)
    selection["backup_count"] = 0
    ranking["candidate_pool_size"] = _integer(
        ranking.get("candidate_pool_size"), "AI 候选池", 1, 200
    )
    ranking["min_candidates_per_source"] = _integer(
        ranking.get("min_candidates_per_source"), "每来源最低候选", 0, 20
    )
    ranking["max_candidates_per_source"] = _integer(
        ranking.get("max_candidates_per_source"), "每来源最高候选", 1, 50
    )
    ranking["interest_candidate_slots"] = _integer(
        ranking.get("interest_candidate_slots"), "兴趣保留位", 0, 50
    )
    ranking["wildcard_slots"] = _integer(
        ranking.get("wildcard_slots"), "平衡通配位", 0, 50
    )
    ranking["top_scored_count"] = _integer(
        ranking.get("top_scored_count"), "AI 评分新闻数", 1, 50
    )
    ranking["ordinary_selected_count"] = _integer(
        ranking.get("ordinary_selected_count"), "AI 额外选择数", 0, 100
    )
    selected_total = selection["headline_count"] + selection["ordinary_count"]
    ai_total = ranking["top_scored_count"] + ranking["ordinary_selected_count"]
    if ai_total < selected_total:
        raise ValueError("AI 评分数与额外选择数之和不能少于最终展示总数")
    if ranking["candidate_pool_size"] < ai_total:
        raise ValueError("AI 候选池不能小于 AI 最终选择总数")

    for key, label, low, high in (
        ("source_factor_floor", "来源系数下限", 0.0, 2.0),
        ("source_factor_range", "来源系数浮动", 0.0, 2.0),
        ("source_weight_min", "来源权重下限", 0.0, 1.0),
        ("source_weight_max", "来源权重上限", 0.0, 1.0),
        ("corroboration_bonus_2", "双来源加分", 0.0, 100.0),
        ("corroboration_bonus_3", "三来源加分", 0.0, 100.0),
        ("corroboration_bonus_4_plus", "四来源以上加分", 0.0, 100.0),
    ):
        adjustment[key] = _number(adjustment.get(key), label, low, high)
    if adjustment["source_weight_max"] <= adjustment["source_weight_min"]:
        raise ValueError("来源权重上限必须高于下限")
    ranking["score_adjustment"] = adjustment

    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("至少需要一个新闻来源")
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 个来源格式错误")
        source_id = str(raw.get("id") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}", source_id):
            raise ValueError(f"来源 ID {source_id!r} 只能使用小写字母、数字和连字符")
        if source_id in seen:
            raise ValueError(f"来源 ID 重复：{source_id}")
        seen.add(source_id)
        provider = str(raw.get("provider") or "").strip()
        if provider not in {"rss", "google_news"}:
            raise ValueError(f"来源 {source_id} 的抓取方式无效")
        source = {
            "id": source_id,
            "name": str(raw.get("name") or "").strip(),
            "provider": provider,
            "weight": _number(raw.get("weight"), f"{source_id} 权重", 0.0, 1.0),
            "language": str(raw.get("language") or "").strip() or "en",
            "access_type": str(raw.get("access_type") or "free").strip(),
            "tags": [str(tag).strip() for tag in raw.get("tags", []) if str(tag).strip()],
        }
        if not source["name"]:
            raise ValueError(f"来源 {source_id} 缺少名称")
        if source["access_type"] not in {"free", "paid"}:
            raise ValueError(f"来源 {source_id} 的访问类型必须是 free 或 paid")
        if provider == "rss":
            source["rss_url"] = str(raw.get("rss_url") or "").strip()
            if not source["rss_url"].startswith(("http://", "https://")):
                raise ValueError(f"来源 {source_id} 需要有效 RSS URL")
        else:
            source["search"] = str(raw.get("search") or "").strip()
            if not source["search"]:
                raise ValueError(f"来源 {source_id} 需要 Google News 搜索式")
            source["google_hl"] = str(raw.get("google_hl") or "en-US").strip()
            source["google_gl"] = str(raw.get("google_gl") or "US").strip()
            source["google_ceid"] = str(raw.get("google_ceid") or "US:en").strip()
        sources.append(source)

    interests = dict(payload.get("interests") or {})
    normalized_interests = {
        "long_term": [
            str(value).strip() for value in interests.get("long_term", []) if str(value).strip()
        ],
        "recent": [
            str(value).strip() for value in interests.get("recent", []) if str(value).strip()
        ],
    }
    return {
        "timezone": timezone,
        "fetch": fetch,
        "filtering": filtering,
        "deduplication": dedup,
        "selection": selection,
        "ranking": ranking,
        "sources": sources,
        "interests": normalized_interests,
    }


def _save_settings(config_dir: Path, payload: Any) -> dict[str, Any]:
    clean = _validate_settings(payload)
    pipeline_path = config_dir / "pipeline.yaml"
    sources_path = config_dir / "sources.yaml"
    interests_path = config_dir / "interests.yaml"
    old_config_hash = load_config(config_dir).config_hash
    old_pipeline = _read_yaml(pipeline_path)
    old_sources = sources_path.read_text(encoding="utf-8")
    old_interests = interests_path.read_text(encoding="utf-8")
    old_pipeline_text = pipeline_path.read_text(encoding="utf-8")

    new_pipeline = dict(old_pipeline)
    for key in ("timezone", "fetch", "filtering", "deduplication", "selection"):
        new_pipeline[key] = clean[key]
    old_ranking = dict(old_pipeline.get("ranking") or {})
    old_ranking.update(clean["ranking"])
    new_pipeline["ranking"] = old_ranking

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = config_dir / "backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(pipeline_path, backup_dir / pipeline_path.name)
    shutil.copy2(sources_path, backup_dir / sources_path.name)
    shutil.copy2(interests_path, backup_dir / interests_path.name)
    try:
        atomic_write_text(
            pipeline_path,
            yaml.safe_dump(new_pipeline, allow_unicode=True, sort_keys=False),
        )
        atomic_write_text(
            sources_path,
            yaml.safe_dump({"sources": clean["sources"]}, allow_unicode=True, sort_keys=False),
        )
        atomic_write_text(
            interests_path,
            yaml.safe_dump(clean["interests"], allow_unicode=True, sort_keys=False),
        )
        new_config = load_config(config_dir)
    except Exception:
        atomic_write_text(pipeline_path, old_pipeline_text)
        atomic_write_text(sources_path, old_sources)
        atomic_write_text(interests_path, old_interests)
        raise
    requires_full_run = new_config.config_hash != old_config_hash
    return {
        "ok": True,
        "backup": str(backup_dir),
        "requires_full_run": requires_full_run,
        "settings": _settings_payload(config_dir),
    }


def _recent_newsletters(config: AppConfig, limit: int = 20) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    archive = config.paths["archive"]
    if not archive.is_dir():
        return entries
    pattern = re.compile(r"^newsletter-(\d{8})-(\d+)\.html$")
    for path in archive.glob("*/*.html"):
        match = pattern.match(path.name)
        if not match:
            continue
        date_value, edition = match.groups()
        relative = path.relative_to(archive).as_posix()
        entries.append(
            {
                "date": f"{date_value[:4]}-{date_value[4:6]}-{date_value[6:]}",
                "edition": int(edition),
                "name": path.name,
                "url": f"/archive/{relative}",
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
            }
        )
    entries.sort(key=lambda row: (row["date"], row["edition"]), reverse=True)
    return entries[:limit]


def _refresh_environment(state: ControlState) -> None:
    state.add_log("info", "开始检查本机运行环境。")
    environment = dict(state.environment)
    try:
        config = load_config(state.config_dir)
        environment["config"] = {"ok": True, "detail": "配置结构有效"}
        state.add_log("success", "配置文件检查通过。")
        try:
            health = client_from_config(
                dict(config.pipeline.get("opencode") or {}), config.root
            ).health()
            environment["opencode"] = {
                "ok": bool(health.get("healthy")),
                "detail": f"OpenCode {health.get('version', '')} · {health.get('mode', '')}",
            }
            state.add_log("success", environment["opencode"]["detail"])
        except PermissionError:
            environment["opencode"] = {
                "ok": None,
                "detail": "当前预览宿主限制执行；双击启动器时会重新检测",
            }
            state.add_log("warning", "当前预览宿主限制 OpenCode 检测；正常双击启动不受影响。")
        except Exception as exc:
            if getattr(exc, "winerror", None) == 5 or "[WinError 5]" in str(exc):
                environment["opencode"] = {
                    "ok": None,
                    "detail": "当前预览宿主限制执行；双击启动器时会重新检测",
                }
                state.add_log("warning", "当前预览宿主限制 OpenCode 检测；正常双击启动不受影响。")
            else:
                environment["opencode"] = {"ok": False, "detail": str(exc)}
                state.add_log("error", f"OpenCode 检查失败：{exc}")
    except Exception as exc:
        environment["config"] = {"ok": False, "detail": str(exc)}
        environment["opencode"] = {"ok": False, "detail": "配置无效，尚未检查"}
        state.add_log("error", f"配置检查失败：{exc}")
    environment["checking"] = False
    with state.lock:
        state.environment = environment


def _run_generation(state: ControlState, force_full: bool) -> None:
    handler = UiLogHandler(state)
    handler.setFormatter(logging.Formatter("%(name)s · %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        config = load_config(state.config_dir)
        run_date = datetime.now(ZoneInfo(config.timezone)).date().isoformat()
        mode = generation_mode(config, run_date)
        state.add_log("info", f"准备执行：{'强制完整运行' if force_full else mode['label']}。")
        lock_path = config.paths["runs"] / ".newsletter.lock"
        with RunLock(lock_path):
            context = RunContext.create(config.paths["runs"], run_date, config.config_hash)
            result = run_auto_pipeline(context, config, force_full=force_full)
        with state.lock:
            state.state = "success"
            state.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            state.last_result = result
            state.last_error = None
        state.add_log("success", f"简报生成成功：{result.get('run_id')}")
    except Exception as exc:
        with state.lock:
            state.state = "error"
            state.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            state.last_error = str(exc)
        state.add_log("error", f"生成失败：{type(exc).__name__}: {exc}")
        logger.debug("generation failed\n%s", traceback.format_exc())
    finally:
        root_logger.removeHandler(handler)


class NewsletterHandler(BaseHTTPRequestHandler):
    server: "NewsletterServer"

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("web: " + format, *args)

    def _send_json(self, value: Any, status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, *, cache: bool = False) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=300" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("请求正文大小无效")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        expected = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
        return origin == expected

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path in {"", "/"}:
            index_path = ROOT_INDEX if ROOT_INDEX.is_file() else ASSET_ROOT / "index.html"
            self._send_file(index_path)
            return
        if parsed.path == "/api/status":
            query = parsed.query.split("after=", 1)
            try:
                after = int(query[1].split("&", 1)[0]) if len(query) == 2 else 0
            except ValueError:
                after = 0
            self._send_json(self.server.state.snapshot(after=max(0, after)))
            return
        if parsed.path == "/api/history":
            try:
                config = load_config(self.server.state.config_dir)
                self._send_json({"items": _recent_newsletters(config)})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/settings":
            try:
                self._send_json(_settings_payload(self.server.state.config_dir))
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        if parsed.path.startswith("/archive/"):
            try:
                config = load_config(self.server.state.config_dir)
                archive = config.paths["archive"].resolve()
                relative = Path(unquote(parsed.path[len("/archive/") :]))
                target = (archive / relative).resolve()
                target.relative_to(archive)
                self._send_file(target)
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        asset_name = parsed.path.lstrip("/")
        if asset_name.startswith("newsletter/ui/"):
            asset_name = asset_name[len("newsletter/ui/") :]
        try:
            target = (ASSET_ROOT / asset_name).resolve()
            target.relative_to(ASSET_ROOT.resolve())
            self._send_file(target, cache=asset_name != "index.html")
        except Exception:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._same_origin():
            self._send_json({"error": "origin rejected"}, 403)
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/shutdown":
            self._send_json({"ok": True, "message": "控制中心正在停止"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if parsed.path == "/api/generate":
            try:
                payload = self._json_body()
            except Exception as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            with self.server.state.lock:
                if self.server.state.state == "running":
                    self._send_json({"error": "管线已经在运行"}, 409)
                    return
                self.server.state.state = "running"
                self.server.state.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
                self.server.state.finished_at = None
                self.server.state.last_error = None
                self.server.state.last_result = None
            thread = threading.Thread(
                target=_run_generation,
                args=(self.server.state, bool(payload.get("force_full", False))),
                daemon=True,
                name="newsletter-generation",
            )
            thread.start()
            self._send_json({"ok": True, "state": "running"}, 202)
            return
        if parsed.path == "/api/environment/refresh":
            threading.Thread(
                target=_refresh_environment,
                args=(self.server.state,),
                daemon=True,
            ).start()
            self._send_json({"ok": True}, 202)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        if not self._same_origin():
            self._send_json({"error": "origin rejected"}, 403)
            return
        if urlsplit(self.path).path != "/api/settings":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with self.server.state.lock:
            if self.server.state.state == "running":
                self._send_json({"error": "管线运行期间不能修改设置"}, 409)
                return
        try:
            payload = self._json_body()
            result = _save_settings(self.server.state.config_dir, payload)
            if result["requires_full_run"]:
                self.server.state.add_log("success", "持久设置已保存；下一次生成将执行完整运行。")
            else:
                self.server.state.add_log("success", "一次性兴趣已保存；成功生成后会自动清空。")
            self._send_json(result)
        except Exception as exc:
            self.server.state.add_log("error", f"设置保存失败：{exc}")
            self._send_json({"error": str(exc)}, 400)


class NewsletterServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: ControlState):
        super().__init__(address, NewsletterHandler)
        self.state = state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private Newsletter local control center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("For safety, the control center only binds to localhost")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    state = ControlState(Path(args.config).resolve())
    state.add_log("info", f"Private Newsletter {__version__} 控制台已启动。")
    server = NewsletterServer(("127.0.0.1", args.port), state)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=_refresh_environment, args=(state,), daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"Private Newsletter control center: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever(poll_interval=0.35)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
