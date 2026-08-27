#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_google_web_translate.py — Google Translate 网页版独立测试脚本

不修改任何生产代码。此脚本只做一件事：用 Playwright 驱动 Chromium 打开
translate.google.com 网页版，逐条提交 selected_news.json 中非中文新闻的
title / summary，取回中文结果，验证"网页版通道"是否可用（区别于 gtx API 通道）。

用法（必须在 Windows 端 Python 运行，因为只有 Windows 端有网络 + Playwright）：
  python test_google_web_translate.py [--json output/selected_news.json]
                                      [--output data/translation/google_web_test.json]
                                      [--max-per-group 30] [--headed]

输出：
  data/translation/google_web_test.json
    每条翻译一项记录：
    { item_index, kind(title|summary), language, original, translated,
      elapsed_seconds, batch, success }

冻结原则：所有网络请求均发生在 Windows Python（Playwright/Chromium）内执行，
本脚本不改变项目任何生产文件。
"""
import sys
import os
import json
import time
import argparse
import traceback

from collections import OrderedDict

WINDOWS_PATH = r"D:\AI工作\private-newsletter-win"


def load_selected(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("headlines", []) + data.get("ordinary", [])


def build_items(selected: list, max_per_group: int) -> list:
    """提取非中文新闻，按 language 分组，每组最多 max_per_group 条。

    返回 (news_list, group_info)：
      news_list: [{item_index, language, title, summary}]
      group_info: {language: (start_idx, count)}
    """
    non_zh = [i for i in selected if (i.get("language") or "en").lower() != "zh"]

    groups = OrderedDict()
    for i in non_zh:
        groups.setdefault(i.get("language") or "en", []).append(i)

    news_list = []
    group_info = {}
    counter = 0
    for lang, items in groups.items():
        picked = items[:max_per_group]
        group_info[lang] = (len(news_list), len(picked))
        for it in picked:
            counter += 1
            news_list.append({
                "item_index": counter,
                "language": lang,
                "title": it.get("title", ""),
                "summary": it.get("summary", ""),
            })
    return news_list, group_info


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def safe_text(page, timeout_ms=4000) -> str:
    """读取结果文本：优先 span[lang=zh-CN]，备用 jsname=W297wb。"""
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


def translate_via_web(page, text: str, timeout_s: int = 12) -> tuple:
    """在已打开的 translate.google.com 页面翻译一段文本。

    Returns: (translated, elapsed_seconds, error_or_none)
    """
    text = (text or "").strip()
    if not text:
        return "", 0.0, None

    t0 = time.time()
    try:
        area = page.locator("textarea").first
        area.wait_for(timeout=8000)
        area.fill(text)
        # 显式提交（网页版通常自动翻译，ctrl+Enter 兜底）
        area.press("Control+Enter")
    except Exception as e:
        return text, 0.0, f"INPUT_ERROR: {str(e)[:80]}"

    # 等待结果出现且非空（排除验证码/CDN 阻塞页）
    deadline = time.time() + timeout_s
    translated = ""
    while time.time() < deadline:
        r = safe_text(page, timeout_ms=3000)
        if r and r != text:
            translated = r
            break
        time.sleep(0.4)

    elapsed = round(time.time() - t0, 2)
    if not translated:
        # 检测是否撞上风控页
        title = ""
        try:
            title = page.title()
        except Exception:
            pass
        return text, elapsed, f"NO_RESULT (page title: {title[:40]})"
    return translated, elapsed, None


def run(job_json, out_json, max_per_group, headed):
    selected = load_selected(job_json)
    news_list, group_info = build_items(selected, max_per_group)
    total_units = 0
    for n in news_list:
        total_units += (1 if n["title"] else 0) + (1 if n["summary"] else 0)

    log(f"selected_news 来源: {job_json}")
    log(f"非中文新闻: {len(news_list)} 条; 分组: {json.dumps({k: v[1] for k, v in group_info.items()}, ensure_ascii=False)}")
    log(f"预计翻译单元: {total_units} (title + summary)")

    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = ctx.new_page()

        unit_no = 0
        fail_units = 0
        try:
            for n in news_list:
                lang = n["language"]
                for kind in ("title", "summary"):
                    text = n[kind]
                    if not text:
                        continue
                    unit_no += 1
                    rec = {
                        "item_index": n["item_index"],
                        "kind": kind,
                        "language": lang,
                        "original": text,
                        "translated": "",
                        "elapsed_seconds": 0.0,
                        "batch": f"{lang}#{n['item_index']}",
                        "success": False,
                    }
                    log(f"[{unit_no}/{total_units}] {lang} {kind} #{n['item_index']} 耗时...")
                    try:
                        page.goto(
                            "https://translate.google.com/?sl=auto&tl=zh-CN&op=translate",
                            timeout=30000,
                        )
                        tr, elapsed, err = translate_via_web(page, text)
                        rec["translated"] = tr
                        rec["elapsed_seconds"] = elapsed
                        rec["success"] = (err is None)
                        if err:
                            rec["error"] = err
                            rec["original"] = text
                            fail_units += 1
                            log(f"    FAIL: {err}")
                        else:
                            log(f"    OK ({elapsed}s): {tr[:50]}")
                    except Exception as e:
                        rec["error"] = f"EXC: {str(e)[:100]}"
                        fail_units += 1
                        log(f"    EXCEPTION: {str(e)[:100]}")
                        traceback.print_exc(limit=2)
                    results.append(rec)
        finally:
            browser.close()

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok = sum(1 for r in results if r["success"])
    log(f"完成: {ok}/{len(results)} 成功, 输出: {out_json}")
    return 0 if fail_units == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Google Translate 网页版测试")
    parser.add_argument("--json", default=os.path.join(WINDOWS_PATH, "output", "selected_news.json"))
    parser.add_argument("--output", default=os.path.join(WINDOWS_PATH, "data", "translation", "google_web_test.json"))
    parser.add_argument("--max-per-group", type=int, default=30)
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口（默认 headless）")
    args = parser.parse_args()
    sys.exit(run(args.json, args.output, args.max_per_group, args.headed))


if __name__ == "__main__":
    main()