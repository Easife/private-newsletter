#!/usr/bin/env python3
"""
RSS 来源测试脚本 - 第二轮实际抓取验证

在 Windows 环境运行：
    python test_rss_fetch.py

输出：
    data/rss_source_test/test_results.json  - 完整 RSS 数据
    data/rss_source_test/test_report.md     - 测试报告
"""

import json
import os
import sys
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup


# ============================================================
# 测试来源配置
# ============================================================

TEST_SOURCES = [
    {
        "name": "BBC",
        "name_zh": "BBC",
        "rss_url": "https://feeds.bbci.co.uk/news/rss.xml",
        "language": "en",
        "access_type": "free",
    },
    {
        "name": "BBC Chinese",
        "name_zh": "BBC 中文",
        "rss_url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        "language": "zh",
        "access_type": "free",
    },
    {
        "name": "NYT Chinese",
        "name_zh": "纽约时报中文网",
        "rss_url": "https://cn.nytimes.com/rss/",
        "language": "zh",
        "access_type": "free",
    },
    {
        "name": "The Guardian",
        "name_zh": "卫报",
        "rss_url": "https://www.theguardian.com/world/rss",
        "language": "en",
        "access_type": "free",
    },
    {
        "name": "DW",
        "name_zh": "德国之声",
        "rss_url": "https://rss.dw.com/rdf/rss-en-all",
        "language": "en",
        "access_type": "free",
    },
    {
        "name": "Al Jazeera",
        "name_zh": "半岛电视台",
        "rss_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "language": "en",
        "access_type": "free",
    },
    {
        "name": "Politico Europe",
        "name_zh": "Politico Europe",
        "rss_url": "https://www.politico.eu/feed/rss/",
        "language": "en",
        "access_type": "free",
    },
]


# ============================================================
# 工具函数
# ============================================================

def clean_html(html: str) -> str:
    """去除 HTML 标签，返回纯文本"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def extract_images_from_html(html: str) -> list[dict]:
    """从 HTML 中提取所有图片 URL"""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src:
            images.append({
                "url": src,
                "alt": img.get("alt", ""),
                "width": img.get("width", ""),
                "height": img.get("height", ""),
            })
    return images


def parse_date(date_str: str) -> dict:
    """尝试解析发布日期"""
    if not date_str:
        return {"raw": "", "parsed": None, "beijing": None, "error": "no date"}
    
    result = {"raw": date_str, "parsed": None, "beijing": None, "error": None}
    
    # feedparser 的 time_struct
    for attr in ["published_parsed", "updated_parsed"]:
        # 这个函数不会被直接调用，只是示意
        pass
    
    # 尝试多种格式
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            result["parsed"] = dt.isoformat()
            # 转换为北京时间 (UTC+8)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            beijing_tz = timezone(timedelta(hours=8))
            beijing_dt = dt.astimezone(beijing_tz)
            result["beijing"] = beijing_dt.strftime("%Y-%m-%d %H:%M:%S")
            return result
        except ValueError:
            continue
    
    result["error"] = f"unparseable: {date_str[:50]}"
    return result


def check_url_accessible(url: str, timeout: int = 10) -> dict:
    """检查 URL 是否可访问"""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                           headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
        final_url = resp.url
        return {
            "status": resp.status_code,
            "final_url": final_url,
            "redirected": final_url != url,
            "content_type": resp.headers.get("Content-Type", ""),
            "accessible": resp.status_code == 200,
        }
    except Exception as e:
        return {"status": 0, "error": str(e), "accessible": False}


def check_image_accessible(url: str, timeout: int = 10) -> dict:
    """检查图片 URL 是否可访问"""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                           headers={"User-Agent": "Mozilla/5.0"})
        content_type = resp.headers.get("Content-Type", "")
        content_length = resp.headers.get("Content-Length", "")
        return {
            "status": resp.status_code,
            "content_type": content_type,
            "content_length": int(content_length) if content_length else 0,
            "is_image": "image" in content_type,
            "accessible": resp.status_code == 200,
        }
    except Exception as e:
        return {"status": 0, "error": str(e), "accessible": False}


# ============================================================
# 主测试逻辑
# ============================================================

def fetch_and_analyze_source(source: dict) -> dict:
    """抓取并分析单个来源"""
    print(f"\n{'='*60}")
    print(f"抓取: {source['name_zh']} ({source['name']})")
    print(f"URL: {source['rss_url']}")
    print(f"{'='*60}")
    
    result = {
        "source": source,
        "fetch_status": "unknown",
        "feed_type": "unknown",
        "items": [],
        "stats": {},
    }
    
    try:
        # 使用 requests 获取（带超时）
        resp = requests.get(
            source["rss_url"],
            timeout=20,
            headers={"User-Agent": "PrivateNewsletter/1.0 (test)"},
        )
        resp.raise_for_status()
        result["fetch_status"] = "success"
        result["response_size"] = len(resp.content)
        print(f"  HTTP {resp.status_code}, 响应 {len(resp.content)} bytes")
        
        # feedparser 解析
        feed = feedparser.parse(resp.content)
        
        # 检测 feed 类型
        if hasattr(feed, 'version'):
            result["feed_type"] = feed.version
        print(f"  Feed 类型: {result['feed_type']}")
        print(f"  新闻条数: {len(feed.entries)}")
        
        # 分析每个 entry
        for i, entry in enumerate(feed.entries):
            item = analyze_entry(entry, source, i)
            result["items"].append(item)
        
        # 计算统计
        result["stats"] = compute_stats(result["items"])
        
        # 打印摘要
        print_stats(result["stats"], source["name_zh"])
        
    except requests.exceptions.Timeout:
        result["fetch_status"] = "timeout"
        print(f"  ❌ 请求超时")
    except requests.exceptions.RequestException as e:
        result["fetch_status"] = f"error: {e}"
        print(f"  ❌ 请求失败: {e}")
    except Exception as e:
        result["fetch_status"] = f"error: {e}"
        print(f"  ❌ 未知错误: {e}")
    
    return result


def analyze_entry(entry: Any, source: dict, index: int) -> dict:
    """分析单个 RSS entry"""
    item = {
        "index": index,
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "published_raw": entry.get("published", entry.get("updated", "")),
        "published": None,
        "summary_raw": entry.get("summary", entry.get("description", "")),
        "summary_text": "",
        "summary_length": 0,
        "content_raw": "",
        "content_text": "",
        "content_length": 0,
        "has_full_content": False,
        "author": entry.get("author", ""),
        "categories": entry.get("categories", []),
        "guid": entry.get("id", entry.get("guid", "")),
        "enclosures": [],
        "media_content": [],
        "media_thumbnail": "",
        "images_in_html": [],
        "image_url": "",
        "raw_fields": {},
    }
    
    # 保存所有原始字段
    for key in entry.keys():
        if key not in ["title", "link", "published", "updated", "summary", "description",
                       "author", "categories", "id", "guid"]:
            val = entry[key]
            if isinstance(val, (str, int, float, bool)):
                item["raw_fields"][key] = val
            elif isinstance(val, list):
                item["raw_fields"][key] = str(val)[:200]
    
    # Summary 处理
    summary_raw = item["summary_raw"]
    if summary_raw:
        # 检查是否包含 HTML
        if "<" in summary_raw:
            item["images_in_html"] = extract_images_from_html(summary_raw)
            item["summary_text"] = clean_html(summary_raw)
        else:
            item["summary_text"] = summary_raw.strip()
        item["summary_length"] = len(item["summary_text"])
    
    # Content:encoded 处理 (feedparser 存为 content)
    content_list = entry.get("content", [])
    if content_list and isinstance(content_list, list):
        for c in content_list:
            if isinstance(c, dict):
                val = c.get("value", "")
                if val:
                    item["content_raw"] = val
                    item["content_text"] = clean_html(val)
                    item["content_length"] = len(item["content_text"])
                    item["has_full_content"] = item["content_length"] > 500
                    break
    
    # Media content (feedparser 的 media_* 字段)
    media_content = entry.get("media_content", [])
    if media_content:
        for mc in media_content:
            if isinstance(mc, dict):
                item["media_content"].append({
                    "url": mc.get("url", ""),
                    "type": mc.get("type", ""),
                    "medium": mc.get("medium", ""),
                    "width": mc.get("width", ""),
                    "height": mc.get("height", ""),
                })
    
    media_thumbnail = entry.get("media_thumbnail", [])
    if media_thumbnail:
        for mt in media_thumbnail:
            if isinstance(mt, dict):
                item["media_thumbnail"] = mt.get("url", "")
                break
    
    # Enclosures
    enclosures = entry.get("enclosures", [])
    if enclosures:
        for enc in enclosures:
            if isinstance(enc, dict):
                item["enclosures"].append({
                    "url": enc.get("href", enc.get("url", "")),
                    "type": enc.get("type", ""),
                    "length": enc.get("length", ""),
                })
    
    # 确定主图片 URL
    if item["media_content"]:
        item["image_url"] = item["media_content"][0]["url"]
    elif item["media_thumbnail"]:
        item["image_url"] = item["media_thumbnail"]
    elif item["images_in_html"]:
        item["image_url"] = item["images_in_html"][0]["url"]
    
    # 发布时间
    item["published"] = parse_date(item["published_raw"])
    
    return item


def compute_stats(items: list[dict]) -> dict:
    """计算来源统计"""
    stats = {
        "total": len(items),
        "has_summary": 0,
        "has_content": 0,
        "has_full_content": 0,
        "has_image": 0,
        "has_html_in_summary": 0,
        "summary_lengths": [],
        "content_lengths": [],
        "image_fields": {},
    }
    
    for item in items:
        if item["summary_length"] > 0:
            stats["has_summary"] += 1
            stats["summary_lengths"].append(item["summary_length"])
        
        if item["content_length"] > 0:
            stats["has_content"] += 1
            stats["content_lengths"].append(item["content_length"])
        
        if item["has_full_content"]:
            stats["has_full_content"] += 1
        
        if item["image_url"]:
            stats["has_image"] += 1
        
        if item["images_in_html"]:
            stats["has_html_in_summary"] += 1
        
        # 统计图片来源字段
        if item["media_content"]:
            stats["image_fields"]["media_content"] = stats["image_fields"].get("media_content", 0) + 1
        if item["media_thumbnail"]:
            stats["image_fields"]["media_thumbnail"] = stats["image_fields"].get("media_thumbnail", 0) + 1
        if item["images_in_html"]:
            stats["image_fields"]["html_img"] = stats["image_fields"].get("html_img", 0) + 1
    
    # 计算长度统计
    if stats["summary_lengths"]:
        stats["summary_avg"] = sum(stats["summary_lengths"]) / len(stats["summary_lengths"])
        stats["summary_median"] = sorted(stats["summary_lengths"])[len(stats["summary_lengths"]) // 2]
        stats["summary_min"] = min(stats["summary_lengths"])
        stats["summary_max"] = max(stats["summary_lengths"])
    
    if stats["content_lengths"]:
        stats["content_avg"] = sum(stats["content_lengths"]) / len(stats["content_lengths"])
        stats["content_median"] = sorted(stats["content_lengths"])[len(stats["content_lengths"]) // 2]
        stats["content_min"] = min(stats["content_lengths"])
        stats["content_max"] = max(stats["content_lengths"])
    
    return stats


def print_stats(stats: dict, name: str):
    """打印统计"""
    print(f"\n  --- {name} 统计 ---")
    print(f"  新闻总数: {stats['total']}")
    print(f"  有摘要: {stats['has_summary']}")
    print(f"  有全文: {stats['has_content']} (完整正文: {stats['has_full_content']})")
    print(f"  有图片: {stats['has_image']}")
    print(f"  Summary 含 HTML: {stats['has_html_in_summary']}")
    
    if stats.get("summary_lengths"):
        print(f"  Summary 长度: avg={stats['summary_avg']:.0f}, "
              f"median={stats['summary_median']}, "
              f"min={stats['summary_min']}, max={stats['summary_max']}")
    
    if stats.get("content_lengths"):
        print(f"  Content 长度: avg={stats['content_avg']:.0f}, "
              f"median={stats['content_median']}, "
              f"min={stats['content_min']}, max={stats['content_max']}")
    
    if stats["image_fields"]:
        print(f"  图片来源: {stats['image_fields']}")


# ============================================================
# 深度审计：检查全文和图片
# ============================================================

def deep_audit_source(result: dict, sample_count: int = 5) -> dict:
    """深度审计：检查全文、图片、URL 可访问性"""
    source_name = result["source"]["name"]
    print(f"\n--- 深度审计: {source_name} ---")
    
    audit = {
        "full_content_samples": [],
        "image_samples": [],
        "url_samples": [],
        "date_samples": [],
    }
    
    items = result["items"]
    if not items:
        return audit
    
    # 选取样本
    sample_indices = list(range(min(sample_count, len(items))))
    
    for idx in sample_indices:
        item = items[idx]
        
        # 全文检查
        if item["has_full_content"]:
            sample = {
                "title": item["title"][:80],
                "content_length": item["content_length"],
                "content_preview": item["content_text"][:300],
                "has_paywall_hint": "付费" in item["content_text"] or "subscribe" in item["content_text"].lower(),
            }
            audit["full_content_samples"].append(sample)
            print(f"  [全文] {item['title'][:50]}... ({item['content_length']} 字符)")
        
        # 图片检查
        if item["image_url"]:
            img_check = check_image_accessible(item["image_url"])
            sample = {
                "title": item["title"][:50],
                "image_url": item["image_url"][:100],
                "field": "media_content" if item["media_content"] else "media_thumbnail" if item["media_thumbnail"] else "html_img",
                "check": img_check,
            }
            audit["image_samples"].append(sample)
            status = "✅" if img_check.get("accessible") else "❌"
            print(f"  [图片] {status} {item['title'][:40]}... -> {item['image_url'][:60]}")
        
        # URL 检查
        if item["link"]:
            url_check = check_url_accessible(item["link"])
            sample = {
                "title": item["title"][:50],
                "raw_url": item["link"],
                "check": url_check,
            }
            audit["url_samples"].append(sample)
            status = "✅" if url_check.get("accessible") else "❌"
            redirect = " → " + url_check["final_url"][:50] if url_check.get("redirected") else ""
            print(f"  [URL] {status} {item['link'][:60]}{redirect}")
        
        # 日期检查
        if item["published"]:
            audit["date_samples"].append({
                "title": item["title"][:50],
                "raw": item["published"]["raw"],
                "beijing": item["published"]["beijing"],
                "error": item["published"]["error"],
            })
    
    return audit


# ============================================================
# 生成报告
# ============================================================

def generate_report(all_results: list[dict], all_audits: dict) -> str:
    """生成 Markdown 测试报告"""
    lines = []
    lines.append("# RSS 来源测试报告（第二轮实际抓取）")
    lines.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # 1. 总体表
    lines.append("## 1. 总体表")
    lines.append("")
    lines.append("| 来源 | RSS | 抓取状态 | 新闻数 | Summary | 全文 | 图片 | 图片字段 | URL | 阅读 |")
    lines.append("|------|-----|----------|--------|---------|------|------|----------|-----|------|")
    
    for result in all_results:
        src = result["source"]
        stats = result["stats"]
        status = "✅" if result["fetch_status"] == "success" else "❌"
        summary = f"✅ {stats.get('summary_avg', 0):.0f}字" if stats.get("summary_lengths") else "❌"
        full = f"✅ {stats['has_full_content']}" if stats.get("has_full_content") else "❌"
        img = f"✅ {stats['has_image']}" if stats.get("has_image") else "❌"
        img_field = ", ".join(stats.get("image_fields", {}).keys()) or "无"
        url = "✅" if stats["total"] > 0 else "❌"
        access = src.get("access_type", "?")
        
        lines.append(f"| {src['name_zh']} | ✅ | {status} {result.get('response_size', 0)//1024}KB | "
                     f"{stats['total']} | {summary} | {full} | {img} | {img_field} | {url} | {access} |")
    
    lines.append("")
    
    # 2. 内容统计
    lines.append("## 2. 内容统计")
    lines.append("")
    for result in all_results:
        stats = result["stats"]
        src = result["source"]
        lines.append(f"### {src['name_zh']} ({src['name']})")
        lines.append(f"- 新闻数量: {stats['total']}")
        lines.append(f"- 有摘要: {stats['has_summary']}")
        lines.append(f"- 有全文: {stats['has_content']} (完整正文: {stats['has_full_content']})")
        lines.append(f"- 有图片: {stats['has_image']}")
        lines.append(f"- Summary 含 HTML: {stats['has_html_in_summary']}")
        if stats.get("summary_lengths"):
            lines.append(f"- Summary 平均长度: {stats['summary_avg']:.0f} 字符")
            lines.append(f"- Summary 中位数: {stats['summary_median']} 字符")
            lines.append(f"- Summary 范围: {stats['summary_min']}~{stats['summary_max']} 字符")
        if stats.get("content_lengths"):
            lines.append(f"- Content 平均长度: {stats['content_avg']:.0f} 字符")
            lines.append(f"- Content 中位数: {stats['content_median']} 字符")
            lines.append(f"- Content 范围: {stats['content_min']}~{stats['content_max']} 字符")
        lines.append("")
    
    # 3. 图片统计
    lines.append("## 3. 图片统计")
    lines.append("")
    lines.append("| 来源 | 图片字段 | 有图片 | 图片可访问 |")
    lines.append("|------|----------|--------|------------|")
    for result in all_results:
        stats = result["stats"]
        src = result["source"]
        fields = ", ".join(stats.get("image_fields", {}).keys()) or "无"
        img_count = stats.get("has_image", 0)
        
        # 检查图片可访问性
        audit = all_audits.get(src["name"], {})
        img_samples = audit.get("image_samples", [])
        accessible = sum(1 for s in img_samples if s.get("check", {}).get("accessible"))
        
        lines.append(f"| {src['name_zh']} | {fields} | {img_count} | {accessible}/{len(img_samples)} |")
    lines.append("")
    
    # 4. 真实样本
    lines.append("## 4. 真实样本")
    lines.append("")
    for result in all_results:
        src = result["source"]
        lines.append(f"### {src['name_zh']}")
        lines.append("")
        
        for item in result["items"][:3]:
            lines.append(f"**标题:** {item['title']}")
            lines.append(f"- 原始 URL: {item['link']}")
            lines.append(f"- Summary 长度: {item['summary_length']} 字符")
            lines.append(f"- Content 长度: {item['content_length']} 字符")
            lines.append(f"- 有全文: {'是' if item['has_full_content'] else '否'}")
            lines.append(f"- 图片 URL: {item['image_url'][:80] if item['image_url'] else '无'}")
            lines.append(f"- 图片字段: {'media_content' if item['media_content'] else 'media_thumbnail' if item['media_thumbnail'] else 'html_img' if item['images_in_html'] else '无'}")
            lines.append(f"- 发布时间: {item['published_raw']}")
            if item['published'] and item['published'].get('beijing'):
                lines.append(f"- 北京时间: {item['published']['beijing']}")
            lines.append(f"- 作者: {item['author']}")
            lines.append(f"- 分类: {item['categories']}")
            
            # 展示 summary 预览
            if item["summary_text"]:
                preview = item["summary_text"][:200]
                lines.append(f"- Summary 预览: {preview}...")
            
            # 展示 content 预览
            if item["content_text"]:
                preview = item["content_text"][:300]
                lines.append(f"- Content 预览: {preview}...")
            
            lines.append("")
    
    # 5. 去重风险分析
    lines.append("## 5. 去重风险分析")
    lines.append("")
    lines.append("### BBC English vs BBC 中文")
    lines.append("- 需要检查同一事件是否同时出现在两个版本")
    lines.append("- URL 域名不同: bbc.com vs bbc.com/zhongwen")
    lines.append("- 标题语言不同: 英文 vs 中文")
    lines.append("")
    lines.append("### NYT English vs NYT 中文")
    lines.append("- 需要检查同一事件是否同时出现在两个版本")
    lines.append("- URL 域名不同: nytimes.com vs cn.nytimes.com")
    lines.append("- 标题语言不同: 英文 vs 中文")
    lines.append("")
    
    # 6. 结论
    lines.append("## 6. 结论")
    lines.append("")
    lines.append("（基于实际抓取结果填写）")
    lines.append("")
    
    return "\n".join(lines)


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("RSS 来源测试 - 第二轮实际抓取验证")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 创建输出目录
    output_dir = os.path.join(os.path.dirname(__file__), "data", "rss_source_test")
    os.makedirs(output_dir, exist_ok=True)
    
    # 抓取所有来源
    all_results = []
    for source in TEST_SOURCES:
        result = fetch_and_analyze_source(source)
        all_results.append(result)
        time.sleep(1)  # 避免过快请求
    
    # 深度审计
    all_audits = {}
    for result in all_results:
        if result["fetch_status"] == "success" and result["items"]:
            audit = deep_audit_source(result)
            all_audits[result["source"]["name"]] = audit
    
    # 保存完整数据
    # 清理不可序列化的数据
    save_data = []
    for result in all_results:
        save_result = {
            "source": result["source"],
            "fetch_status": result["fetch_status"],
            "feed_type": result.get("feed_type", ""),
            "response_size": result.get("response_size", 0),
            "stats": result["stats"],
            "items": result["items"],
        }
        save_data.append(save_result)
    
    json_path = os.path.join(output_dir, "test_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n完整数据已保存: {json_path}")
    
    # 生成报告
    report = generate_report(all_results, all_audits)
    report_path = os.path.join(output_dir, "test_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"测试报告已保存: {report_path}")
    
    # 打印总结
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)
    for result in all_results:
        src = result["source"]
        stats = result["stats"]
        status = "✅" if result["fetch_status"] == "success" else "❌"
        print(f"{status} {src['name_zh']}: {stats['total']} 条, "
              f"全文 {stats.get('has_full_content', 0)}, "
              f"图片 {stats.get('has_image', 0)}")


if __name__ == "__main__":
    main()
