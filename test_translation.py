#!/usr/bin/env python3
"""
独立测试脚本：
1. OpenCode 免费模型 JSON 输出测试
2. Google Translate 翻译测试（5 条真实新闻）

不在生产 Pipeline 中使用。
运行：Windows 端 python test_translation.py
"""
import sys
import os
import json
import time
import subprocess

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # Windows 上 urllib 不自动读取环境变量代理，必须显式安装
    import urllib.request
    proxy_handler = urllib.request.ProxyHandler({
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    })
    opener = urllib.request.build_opener(proxy_handler)
    urllib.request.install_opener(opener)

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7897"

OPENCODE_BIN = os.path.expanduser("~/.opencode/bin/opencode")
if not os.path.isfile(OPENCODE_BIN):
    OPENCODE_BIN = "opencode"


# ============================================================
# Part 1: OpenCode 免费模型 JSON 输出测试
# ============================================================

FREE_MODELS = [
    "opencode/nemotron-3.5-lightning-free",
    "opencode/hy3-free",
    "opencode/mimo-v2.5-free",
]


def test_opencode_model(model: str, timeout: int = 60) -> dict:
    """测试 OpenCode 模型的 JSON 输出能力"""
    prompt = 'Return ONLY this JSON: {"status":"ok","model_test":true,"items":["one","two","three"]}'
    cmd = [OPENCODE_BIN, "run", "--format", "json", "--model", model]
    t0 = time.time()
    try:
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - t0
        if result.returncode != 0:
            return {"model": model, "ok": False, "elapsed": round(elapsed, 1),
                    "error": result.stderr[:200]}
        text_parts = []
        for line in result.stdout.splitlines():
            try:
                ev = json.loads(line)
                if ev.get("type") == "text":
                    text_parts.append(ev.get("text", ""))
            except Exception:
                continue
        full_text = "".join(text_parts).strip()
        json_ok = False
        try:
            parsed = json.loads(full_text)
            json_ok = parsed.get("status") == "ok" and parsed.get("model_test") is True
        except Exception:
            parsed = None
        return {"model": model, "ok": json_ok, "elapsed": round(elapsed, 1),
                "raw_text": full_text[:120], "parsed": parsed}
    except subprocess.TimeoutExpired:
        return {"model": model, "ok": False, "elapsed": timeout, "error": "TIMEOUT"}


def part1_opencode_test():
    print("=" * 60)
    print("Part 1: OpenCode 免费模型 JSON 输出测试")
    print("=" * 60)
    results = []
    for m in FREE_MODELS:
        r = test_opencode_model(m)
        results.append(r)
        status = "OK" if r["ok"] else "FAIL"
        err = r.get("error", r.get("raw_text", "")[:80])
        print(f"  [{status}] {r['model']:50s} {r['elapsed']:6.1f}s  {err}")
    return results


# ============================================================
# Part 2: Google Translate 翻译测试
# ============================================================

SAMPLE_NEWS = [
    {
        "category": "国际政治",
        "title": "Iran Must Plan to Overcome U.S. Sanctions After Trump's 'Economic D-Day' Threats, Tehran Official Says",
        "summary": "A senior Iranian official said the country must develop a strategy to withstand U.S. sanctions after President Trump threatened what he called 'economic D-Day' against Tehran. The comments came amid escalating tensions between Washington and Iran over nuclear negotiations.",
    },
    {
        "category": "经济/财经",
        "title": "Dalio Says Sell Bonds, Buy Gold, Bitcoin as Debt Crisis Looms",
        "summary": "Ray Dalio, founder of Bridgewater Associates, warned that the U.S. faces a debt crisis and advised investors to sell bonds and buy gold and bitcoin. He cited growing concerns about the long-term sustainability of U.S. fiscal policy and the potential devaluation of the dollar.",
    },
    {
        "category": "科技",
        "title": "Nvidia to Back Ohio Data Center With as Much as $105 Billion",
        "summary": "Nvidia announced plans to invest up to $105 billion in a new data center in Ohio, marking one of the largest corporate infrastructure commitments in recent years. The facility will support AI training and cloud computing workloads.",
    },
    {
        "category": "王室/娱乐（应被排除）",
        "title": "Prince Harry and Meghan Will Move Back to U.K. After 6 Years in U.S.",
        "summary": "Prince Harry and his wife Meghan announced they will relocate to the United Kingdom after six years living in the United States. The move marks a significant shift for the royal couple who stepped back from royal duties in 2020.",
    },
    {
        "category": "普通新闻",
        "title": "Mark Zuckerberg Buys an Irish Castle",
        "summary": "Meta CEO Mark Zuckerberg has purchased a historic castle in County Cork, Ireland, according to local property records. The estate reportedly includes extensive grounds and was previously owned by a private trust.",
    },
]


def translate_via_google(text: str, timeout: int = 15) -> tuple:
    """通过 Google Translate 免费端点翻译
    使用 translate.googleapis.com（公开端点，无需 API key）
    """
    import urllib.request
    import urllib.parse
    url = "https://translate.googleapis.com/translate_a/single"
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": text,
    })
    req = urllib.request.Request(f"{url}?{params}")
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        if data and data[0]:
            translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
            return translated, round(elapsed, 2), None
        return "", round(elapsed, 2), "empty response"
    except Exception as e:
        return "", 0.0, str(e)[:120]


def part2_google_translate():
    print()
    print("=" * 60)
    print("Part 2: Google Translate 翻译测试")
    print("=" * 60)
    print("  使用 Google Translate 公开端点 (translate.googleapis.com)")
    print()
    results = []
    total_t = time.time()
    for i, item in enumerate(SAMPLE_NEWS, 1):
        print(f"--- [{i}] {item['category']} ---")
        title_zh, title_t, title_err = translate_via_google(item["title"])
        print(f"  EN: {item['title'][:80]}")
        if title_err:
            print(f"  ZH (title) ERROR: {title_err}")
        else:
            print(f"  ZH (title): {title_zh}")
            print(f"           ({title_t}s)")
        sum_zh, sum_t, sum_err = translate_via_google(item["summary"])
        if sum_err:
            print(f"  ZH (summary) ERROR: {sum_err}")
        else:
            print(f"  ZH (summary): {sum_zh[:120]}")
            print(f"              ({sum_t}s)")
        print()
        results.append({
            "category": item["category"],
            "title_en": item["title"],
            "title_zh": title_zh,
            "title_t": title_t,
            "summary_en": item["summary"],
            "summary_zh": sum_zh,
            "summary_t": sum_t,
            "error": title_err,
        })
    total_elapsed = time.time() - total_t
    print(f"总耗时: {total_elapsed:.2f}s")
    return results


if __name__ == "__main__":
    print(f"代理: {PROXY}")
    print()
    # Part 1 (OpenCode) 只能在 Linux/WSL 端运行（binary 是 ELF）
    # 测试已在 WSL 端完成
    opencode_results = []
    if sys.platform != "win32" and os.path.isfile(OPENCODE_BIN):
        opencode_results = part1_opencode_test()
    else:
        print("Part 1 (OpenCode): 跳过（Windows 端无法运行 Linux ELF binary）")
        print("Part 1 已在 WSL 端测试：opencode/nemotron-3.5-lightning-free 可用")
        print()
    translate_results = part2_google_translate()
    print()
    print("=" * 60)
    print("汇总")
    print("=" * 60)
    working_models = [r["model"] for r in opencode_results if r["ok"]]
    print(f"可用的 OpenCode 免费模型: {working_models or '(见 WSL 测试结果)'}")
    if translate_results:
        gt_ok = sum(1 for r in translate_results if r.get("title_zh"))
        print(f"Google Translate 成功翻译: {gt_ok}/{len(translate_results)} 条标题")