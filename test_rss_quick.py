#!/usr/bin/env python3
"""
RSS 来源快速测试 - 验证各来源是否可抓取

在 Windows 环境运行：
    python test_rss_quick.py

测试所有配置的 RSS 来源，输出每个来源的状态和条数。
"""
import os
import sys
import yaml
import requests
import feedparser
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows 控制台编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 代理配置
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7897"
PROXIES = {"http": PROXY, "https": PROXY}


def test_source(source, timeout=15):
    """测试单个 RSS 来源"""
    name = source["name"]
    url = source["rss_url"]
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "PrivateNewsletter/1.0"},
            proxies=PROXIES, verify=False,
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        count = len(feed.entries)
        return name, count, "OK", None
    except requests.exceptions.Timeout:
        return name, 0, "TIMEOUT", None
    except requests.exceptions.SSLError as e:
        return name, 0, "SSL_ERROR", str(e)[:80]
    except requests.exceptions.ConnectionError as e:
        return name, 0, "CONN_ERROR", str(e)[:80]
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        return name, 0, f"HTTP_{status}", None
    except Exception as e:
        return name, 0, "ERROR", str(e)[:80]


def main():
    # 加载 sources.yaml
    config_path = os.path.join(os.path.dirname(__file__), "config", "sources.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    sources = config.get("sources", [])

    print(f"测试 {len(sources)} 个 RSS 来源...")
    print(f"代理: {PROXY}")
    print("=" * 60)

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(test_source, s): s for s in sources}
        for future in as_completed(futures):
            results.append(future.result())

    # 按状态排序
    ok = sorted([(n, c, s, e) for n, c, s, e in results if s == "OK"], key=lambda x: -x[1])
    fail = sorted([(n, c, s, e) for n, c, s, e in results if s != "OK"], key=lambda x: x[0])

    print(f"\n成功 ({len(ok)}):")
    for name, count, status, err in ok:
        print(f"  ✅ {name}: {count} 条")

    print(f"\n失败 ({len(fail)}):")
    for name, count, status, err in fail:
        print(f"  ❌ {name}: {status}" + (f" ({err})" if err else ""))

    print(f"\n总计: {sum(c for _, c, _, _ in ok)} 条来自 {len(ok)} 个来源")


if __name__ == "__main__":
    main()
