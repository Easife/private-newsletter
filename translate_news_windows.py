#!/usr/bin/env python3
"""
Windows 端 Google Translate 翻译脚本

输入: --input items.json（list[{item_index, title, summary, language}]）
输出: --output translated.json（list[{item_index, title_zh, summary_zh, err_title, err_summary}]）

代理：自动通过 http://127.0.0.1:7897 访问（Windows Clash）
"""
import sys
import os
import json
import time
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--output", required=True, help="Output JSON file")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        items = json.load(f)

    total = len(items)
    print(f"[Windows Google Translate] 翻译 {total} 条 (proxy: {PROXY})")
    t_start = time.time()

    translated = []
    success_count = 0
    fail_count = 0

    for i, item in enumerate(items, 1):
        lang = item.get("language", "en") or "en"
        title = item.get("title", "")
        summary = item.get("summary", "")

        if lang == "zh":
            # 中文：直接返回原文
            entry = {
                "item_index": item.get("item_index", i),
                "title_zh": title,
                "summary_zh": summary,
                "err_title": None,
                "err_summary": None,
            }
            success_count += 1
        else:
            # 英文、日文、韩文等：调用 Google Translate
            title_zh, _, err_title = google_translate_one(title)
            summary_zh, _, err_sum = google_translate_one(summary)
            entry = {
                "item_index": item.get("item_index", i),
                "title_zh": title_zh,
                "summary_zh": summary_zh,
                "err_title": err_title,
                "err_summary": err_sum,
            }
            if err_title or err_sum:
                fail_count += 1
            else:
                success_count += 1

        translated.append(entry)

        if i % 20 == 0 or i == total:
            elapsed = time.time() - t_start
            avg = elapsed / i
            print(f"  进度 {i}/{total} ({avg:.2f}s/条, 剩余约 {avg*(total-i):.0f}s)")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t_start
    print(f"\n完成: {success_count}/{total} 成功, {fail_count} 失败, {elapsed:.1f}s 总耗时")
    print(f"输出: {args.output}")


if __name__ == "__main__":
    main()