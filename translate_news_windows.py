#!/usr/bin/env python3
"""
Windows 端翻译脚本（默认三层 fallback：Google GTX API → Google Web(Playwright) → 交 LLM）

输入: --input items.json（list[{item_index, title, summary, language}]）
输出: --output translated.json（list[{item_index, title_zh, summary_zh, err_title, err_summary}]）

默认翻译链：
- 第一层 Google GTX API（translate.googleapis.com，client=gtx），批量 + 批间随机延迟
- 第二层 Google Web（Playwright 驱动 Chromium 打开 translate.google.com，逐条真实浏览器翻译）；
  失败条目按语言分组、每组最多 --web-max-per-group（默认 30）条，不混合语言提交
- 第三层：err_* 字段保留错误信息，由 WSL 侧 LLM 兜底

Bing 翻译（bing_translate_one）已默认禁用，仅作备用保留；传 --enable-bing 可临时启用该层。
代理：自动通过 http://127.0.0.1:7897 访问（Windows Clash）。

输出会打印各层成功数量（GTX / Web / Bing / 交 LLM 层），供最终报告统计。
"""
import sys
import os
import json
import time
import random
import urllib.request
import urllib.parse
import re
import argparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 安装全局代理
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7897"
proxy_handler = urllib.request.ProxyHandler({
    "http": PROXY,
    "https": PROXY,
})
opener = urllib.request.build_opener(proxy_handler)
urllib.request.install_opener(opener)

# Bing 快速失败状态：IG 只获取一次；连续失败后禁用 Bing，直接交给 LLM
_BING_IG_CACHE = None
_BING_FAIL_STREAK = 0
_BING_DISABLED_PRINTED = False
BING_MAX_FAIL_STREAK = 3  # 连续 3 次失败后禁用 Bing fallback


def _bing_get_ig(timeout: int = 5) -> str:
    """从 Bing Translator 页面提取 IG 参数（快速失败，不阻塞）"""
    try:
        req = urllib.request.Request(
            "https://www.bing.com/translator?ref=MSTWidget",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
        m = re.search(r'"IG"\s*:\s*"([0-9A-Fa-f]{16,40})"', html)
        return m.group(1) if m else ""
    except Exception:
        return ""


def bing_translate_one(text: str, target: str = "zh-Hans", timeout: int = 5) -> tuple:
    """单条 Bing Translator 翻译（免费端点，无需 API key；默认禁用，仅备用）

    快速失败设计：短超时 + IG 全局缓存（只请求一次）+ 连续失败禁用。
    - IG 只获取一次，后续复用，避免每次翻页请求拖慢
    - Bing 连续失败 BING_MAX_FAIL_STREAK 次后置为禁用，
      后续条目全部直接标记失败（交给 LLM fallback），不再尝试

    Returns:
        (translated_text, elapsed_seconds, error_or_None)
    """
    global _BING_IG_CACHE, _BING_FAIL_STREAK

    text = (text or "").strip()
    if not text:
        return "", 0.0, None

    if re.search(r"[\u4e00-\u9fff]", text):
        return text, 0.0, None

    # 快速失败：连续失败阈值后直接返回失败，不再请求
    if _BING_FAIL_STREAK >= BING_MAX_FAIL_STREAK:
        return text, 0.0, "BING_DISABLED"

    # IG 只获取一次并缓存
    if _BING_IG_CACHE is None:
        _BING_IG_CACHE = _bing_get_ig(timeout=min(timeout, 5))
    ig = _BING_IG_CACHE
    if not ig:
        _BING_FAIL_STREAK += 1
        return text, 0.0, "BING_IG_UNREACHABLE"
    params = urllib.parse.urlencode({
        "isVertical": "1",
        "IG": ig,
        "IID": "translator.5028",
    })
    body = urllib.parse.urlencode({
        "from": "en",
        "to": target,
        "text": text,
    }).encode()
    url = f"https://www.bing.com/ttranslatev3?{params}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.bing.com/translator",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        elapsed = time.time() - t0
        # 响应可能为空（端点风控）→ 视为失败
        if not raw:
            _BING_FAIL_STREAK += 1
            return text, elapsed, "BING_EMPTY_RESPONSE"
        arr = json.loads(raw)
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            tr = arr[0].get("translations", [])
            if tr and isinstance(tr[0], dict) and tr[0].get("text"):
                _BING_FAIL_STREAK = 0  # 成功则重置失败计数
                return tr[0]["text"], round(elapsed, 2), None
            _BING_FAIL_STREAK += 1
            return text, round(elapsed, 2), "BING_NO_TRANSLATION"
        _BING_FAIL_STREAK += 1
        return text, round(elapsed, 2), "BING_BAD_RESPONSE"
    except Exception as e:
        _BING_FAIL_STREAK += 1
        return text, 0.0, f"BING_ERROR: {str(e)[:80]}"


def google_translate_one(text: str, target: str = "zh-CN", timeout: int = 10) -> tuple:
    """单条 Google Translate 翻译"""
    text = (text or "").strip()
    if not text:
        return "", 0.0, None

    # 含中文：直接返回（已是中文，无需翻译）
    if re.search(r"[\u4e00-\u9fff]", text):
        return text, 0.0, None

    url = "https://translate.googleapis.com/translate_a/single"
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "auto",
        "tl": target,
        "dt": "t",
        "q": text,
    })
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        if data and isinstance(data, list) and data[0]:
            translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
            return translated, round(elapsed, 2), None
        return text, round(elapsed, 2), "empty response"
    except Exception as e:
        return text, 0.0, f"GOOGLE_ERROR: {str(e)[:80]}"


def _chunks(lst: list, size: int):
    """按固定大小分批"""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


# ════════════════════════════════════════════════════════════════════
# 第二层：Google Web（Playwright 驱动 Chromium 打开 translate.google.com）
# 方案与独立测试脚本 test_google_web_translate.py 一致。
# 失败条目按语言分组、每组最多 --web-max-per-group 条，不混合语言。
# ════════════════════════════════════════════════════════════════════

_PW = None


def _playwright_module():
    """延迟导入 playwright；不可用时返回 None（该层整体跳过）。"""
    global _PW
    if _PW is None:
        try:
            import playwright.sync_api as _p
            _PW = _p
        except Exception:
            _PW = False
    return _PW or None


_WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _web_read_result(page, timeout_ms=4000) -> str:
    """读取网页版译文：优先 span[lang=zh-CN]，备用 jsname=W297wb。"""
    loc = page.locator('span[lang="zh-CN"]').first
    try:
        loc.wait_for(timeout=timeout_ms)
        t = loc.inner_text(timeout=timeout_ms)
        if t and t.strip():
            return t.strip()
    except Exception:
        pass
    for js in ('span[jsname="W297wb"]', '[jsname="xZ3FQc"]'):
        try:
            el = page.locator(js).first
            el.wait_for(timeout=2000)
            t = el.inner_text(timeout=2000)
            if t and t.strip():
                return t.strip()
        except Exception:
            continue
    return ""


def _web_translate_one(page, text: str, timeout_s: int = 12) -> tuple:
    """在已打开的 translate.google.com 页面翻译一段文本。

    Returns: (translated, elapsed_seconds, error_or_None)
    """
    text = (text or "").strip()
    if not text:
        return "", 0.0, None
    t0 = time.time()
    try:
        page.goto(
            "https://translate.google.com/?sl=auto&tl=zh-CN&op=translate",
            timeout=30000,
        )
        area = page.locator("textarea").first
        area.wait_for(timeout=8000)
        area.fill(text)
        area.press("Control+Enter")
    except Exception as e:
        return text, 0.0, f"WEB_INPUT_ERROR: {str(e)[:80]}"

    translated = ""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = _web_read_result(page, timeout_ms=3000)
        if r and r != text:
            translated = r
            break
        time.sleep(0.4)
    elapsed = round(time.time() - t0, 2)
    if not translated:
        title = ""
        try:
            title = page.title()
        except Exception:
            pass
        return text, elapsed, f"WEB_NO_RESULT (title: {title[:40]})"
    return translated, elapsed, None


def group_into_lang_batches(items: list, batch_size: int) -> list:
    """语言分组 + 分批（发生在所有翻译 provider 之前）。

    1. 按 language 分组（保留原始顺序）；
    2. 每组内再按 batch_size 拆成多个子批（同一语言，不混合其他语言）。

    items: 原始 items（list[{item_index,title,summary,language}]），中文条目会被跳过。
    Returns: list[list[item]]，每个子批全部为同一语言，且 ≤ batch_size 条。
    """
    groups = {}
    for it in items:
        lang = it.get("language", "en") or "en"
        if lang == "zh":
            continue
        groups.setdefault(lang, []).append(it)
    batches = []
    for group in groups.values():
        for start in range(0, len(group), max(1, batch_size)):
            batches.append(group[start:start + batch_size])
    return batches


def google_web_translate_batch(batch: list, headless: bool = True, empty: str = "") -> dict:
    """用 Playwright 翻译一批（同一语言）条目。

    Returns: {f"{index}:{kind}": (translated, elapsed, error_or_None)}
    """
    keys = [f"{s['index']}:{s['kind']}" for s in batch]
    pw = _playwright_module()
    if pw is None:
        return {k: (None, 0.0, "WEB_IMPORT_UNAVAILABLE") for k in keys}
    out = {}
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=_WEB_UA, locale="zh-CN")
            page = ctx.new_page()
            try:
                for s in batch:
                    key = f"{s['index']}:{s['kind']}"
                    out[key] = _web_translate_one(page, s["text"])
            finally:
                browser.close()
    except Exception as e:
        err = f"WEB_LAUNCH_ERROR: {str(e)[:100]}"
        for k in keys:
            out.setdefault(k, (None, 0.0, err))
    for k in keys:
        out.setdefault(k, (None, 0.0, "WEB_NO_DATA"))
    return out


def main():
    global _BING_DISABLED_PRINTED
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument(
        "--batch-size", type=int, default=25,
        help="Google 层分批大小（默认 25，避免一次批量请求过多触发 429）",
    )
    parser.add_argument(
        "--batch-delay-min", type=float, default=2.0,
        help="批间最小随机等待秒数",
    )
    parser.add_argument(
        "--batch-delay-max", type=float, default=8.0,
        help="批间最大随机等待秒数",
    )
    parser.add_argument(
        "--bing-timeout", type=float, default=5.0,
        help="Bing 单次翻译超时秒数（快速失败）",
    )
    parser.add_argument(
        "--bing-max-fail-streak", type=int, default=3,
        help="Bing 连续失败次数上限，超过后禁用 Bing fallback",
    )
    parser.add_argument(
        "--enable-bing", action="store_true",
        help="临时启用 Bing 备用层（默认禁用；位置在 GTX 之后、Web 之前）",
    )
    parser.add_argument(
        "--web-enabled", action="store_true", default=True,
        help="启用 Google Web(Playwright) 层（默认启用）",
    )
    parser.add_argument(
        "--web-headless", action="store_true", default=True,
        help="Playwright Chromium 以 headless 模式运行（默认）",
    )
    parser.add_argument(
        "--web-max-per-group", type=int, default=30,
        help="Google Web 每组语言最多条数（默认 30，超出拆多批）",
    )
    args = parser.parse_args()

    # 允许配置文件覆盖 Bing 快速失败阈值
    global BING_MAX_FAIL_STREAK
    BING_MAX_FAIL_STREAK = args.bing_max_fail_streak

    with open(args.input, "r", encoding="utf-8") as f:
        items = json.load(f)

    total = len(items)
    if args.enable_bing:
        print(f"[Windows Translate] 翻译 {total} 条 (proxy: {PROXY}, 层1 GTX → 层2 Bing → 层3 Web → LLM兜底, batch={args.batch_size})")
    else:
        print(f"[Windows Translate] 翻译 {total} 条 (proxy: {PROXY}, 层1 GTX → 层2 Google Web → LLM兜底, batch={args.batch_size}, Bing 默认禁用)")
    t_start = time.time()

    stat = {
        "zh_pass": 0,
        "title_google": 0, "title_bing": 0, "title_web": 0, "title_failed": 0,
        "sum_google": 0, "sum_bing": 0, "sum_web": 0, "sum_failed": 0,
    }

    # ── 0. 语言分组 + batch 拆分（必须在所有翻译 provider 之前）──
    # 把每条新闻拆成独立的 title/summary 翻译单元，按 language 分组、
    # 每组再按 args.batch_size 拆批。每个语言 batch 独立执行 fallback：
    #   Google GTX → Google Web → LLM（Bing 不参与默认链，保留代码备用）
    def _specs_for_batch(batch):
        specs = []
        for item in batch:
            i = item.get("item_index", 1)
            lang = item.get("language", "en") or "en"
            if lang == "zh":
                continue
            title = item.get("title", "")
            summary = item.get("summary", "")
            if title:
                specs.append({"index": i, "kind": "title", "lang": lang, "text": title})
            if summary:
                specs.append({"index": i, "kind": "summary", "lang": lang, "text": summary})
        return specs

    lang_batches = group_into_lang_batches(items, args.batch_size)

    # 预建 translated 骨架（含中文直通）
    translated = []
    for item in items:
        lang = item.get("language", "en") or "en"
        title = item.get("title", "")
        summary = item.get("summary", "")
        if lang == "zh":
            stat["zh_pass"] += 1
            translated.append({
                "item_index": item.get("item_index", 1),
                "title_zh": title,
                "summary_zh": summary,
                "err_title": None,
                "err_summary": None,
            })
        else:
            translated.append({
                "item_index": item.get("item_index", 1),
                "title_zh": title,
                "summary_zh": summary,
                "err_title": None,
                "err_summary": None,
            })

    t_fallback = time.time()
    for bi, lang_batch in enumerate(lang_batches, 1):
        lang = lang_batch[0]["lang"]
        specs = _specs_for_batch(lang_batch)
        print(f"[Windows] 语言批次 {bi}/{len(lang_batches)} ({lang}#{bi}, {len(specs)} 个单元)")

        # 层1：Google GTX API
        pending = []
        for s in specs:
            tr, _, err = google_translate_one(s["text"])
            rec = next(x for x in translated if x["item_index"] == s["index"])
            skind = s["kind"]
            if err:
                rec["err_title" if skind == "title" else "err_summary"] = err
                pending.append(s)
            else:
                rec["title_zh" if skind == "title" else "summary_zh"] = tr
                stat[f"{'title' if skind=='title' else 'sum'}_google"] += 1
        if pending:
            print(f"  GTX 失败 {len(pending)} 个单元 → Google Web")

        # 层2：Google Web（Playwright）。按批次内再拆 ≤web_max_per_group 子批（同语言无需再分组）
        web_pending = []
        if args.web_enabled and not args.enable_bing and pending:
            web_batches = list(_chunks(pending, args.web_max_per_group))
            for wi, wb in enumerate(web_batches, 1):
                print(f"  Google Web 子批 {wi}/{len(web_batches)} ({lang}): {len(wb)} 条...")
                out = google_web_translate_batch(wb, headless=args.web_headless)
                for s in wb:
                    key = f"{s['index']}:{s['kind']}"
                    tr, elapsed, err = out[key]
                    rec = next(x for x in translated if x["item_index"] == s["index"])
                    skind = s["kind"]
                    if err is None:
                        rec["title_zh" if skind == "title" else "summary_zh"] = tr
                        rec["err_title" if skind == "title" else "err_summary"] = None
                        stat[f"{'title' if skind=='title' else 'sum'}_web"] += 1
                    else:
                        prev = rec["err_title" if skind == "title" else "err_summary"] or ""
                        rec["err_title" if skind == "title" else "err_summary"] = f"{prev} | WEB: {err}"
                        web_pending.append(s)
                    print(f"    [{skind}] #{s['index']} "
                          f"{'OK ' if err is None else 'FAIL'} ({elapsed}s)"
                          f"{' → ' + str(tr)[:40] if err is None else ''}")
        elif args.enable_bing and pending:
            # Bing 备用层（默认禁用；仅 --enable-bing 时启用），位于 GTX 后、Web 前
            print("  Bing 备用层启用...")
            remaining = []
            for s in pending:
                tr, _, err = bing_translate_one(s["text"], timeout=args.bing_timeout)
                rec = next(x for x in translated if x["item_index"] == s["index"])
                skind = s["kind"]
                if not err:
                    rec["title_zh" if skind == "title" else "summary_zh"] = tr
                    rec["err_title" if skind == "title" else "err_summary"] = None
                    stat[f"{'title' if skind=='title' else 'sum'}_bing"] += 1
                else:
                    remaining.append(s)
            web_pending = remaining
        else:
            web_pending = pending

        # 层3：LLM（本脚本不执行，err_* 字段已保留，交由 WSL 侧 LLM 兜底）
        if web_pending:
            print(f"  Google Web 失败 {len(web_pending)} 个单元 → 交 LLM 兜底")

        # 批间随机等待（避免固定模式触发限流）
        if lang_batch is not lang_batches[-1]:
            wait = random.uniform(args.batch_delay_min, args.batch_delay_max)
            print(f"[Windows] 语言批次 {bi} 完成, 随机等待 {wait:.1f}s 后继续")
            time.sleep(wait)

    elapsed = time.time() - t_start
    print(f"[Windows] 翻译提供方阶段耗时: {time.time() - t_fallback:.1f}s")

    # ── 统计与写文件 ─────────────────────────────
    success_count = 0
    fail_count = 0
    for e in translated:
        if e["err_title"] or e["err_summary"]:
            stat["title_failed"] += 1 if e["err_title"] else 0
            stat["sum_failed"] += 1 if e["err_summary"] else 0
            fail_count += 1
        else:
            success_count += 1

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    print(f"\n完成: 条目 {success_count}/{total} 成功, {fail_count} 失败, {elapsed:.1f}s 总耗时")
    print(
        f"分层统计: 标题[GTX {stat['title_google']} | Web {stat['title_web']} "
        f"| Bing {stat['title_bing']} | 交LLM {stat['title_failed']}] "
        f"摘要[GTX {stat['sum_google']} | Web {stat['sum_web']} "
        f"| Bing {stat['sum_bing']} | 交LLM {stat['sum_failed']}] "
        f"中文直通 {stat['zh_pass']}"
    )
    print(f"输出: {args.output}")


if __name__ == "__main__":
    main()