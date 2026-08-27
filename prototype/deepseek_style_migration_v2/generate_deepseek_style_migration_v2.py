#!/usr/bin/env python3
"""
DeepSeek 视觉风格迁移生成器 v0.2.1

第二轮视觉增强：强化 DeepSeek 美术风格。
- 渐变文字
- 背景光晕氛围
- AI Insight 发光区域
- 卡片渐变表面 + 彩色辉光阴影

数据来源：
  - output/selected_news.json（主要）
  - data/daily_run_raw.json（补充）

用法：
  python prototype/deepseek_style_migration_v2/generate_deepseek_style_migration_v2.py
"""

import json
import os
import html as html_module
import urllib.parse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

PAID_SOURCES = {
    "Financial Times", "The Economist", "New York Times",
    "NYT Technology", "Washington Post", "Wall Street Journal",
    "Bloomberg", "日经",
    "FT", "NYT", "NYT Tech", "WSJ", "WaPo", "Economist",
}

SOURCE_DISPLAY = {
    "Reuters": "路透社", "Associated Press": "美联社", "AFP": "法新社",
    "BBC": "BBC", "BBC World": "BBC 世界", "The Guardian": "卫报",
    "Guardian": "卫报",
    "Financial Times": "金融时报", "FT": "金融时报",
    "The Economist": "经济学人", "Economist": "经济学人",
    "New York Times": "纽约时报", "NYT": "纽约时报",
    "NYT Technology": "纽约时报科技版", "NYT Tech": "纽约时报科技版",
    "Washington Post": "华盛顿邮报", "WaPo": "华盛顿邮报",
    "Wall Street Journal": "华尔街日报", "WSJ": "华尔街日报",
    "Bloomberg": "彭博社", "CNBC": "CNBC",
    "NHK World": "NHK", "NHK": "NHK", "日经": "日经新闻",
    "新华社": "新华社", "联合早报": "联合早报",
    "DW": "德国之声", "Al Jazeera": "半岛电视台",
    "NYT Chinese": "纽约时报中文网",
}


def esc(text: str) -> str:
    return html_module.escape(str(text))


def get_display_name(name: str) -> str:
    return SOURCE_DISPLAY.get(name, name)


def is_paid(name: str) -> bool:
    return name in PAID_SOURCES


def google_search_url(title: str) -> str:
    return f"https://www.google.com/search?q={urllib.parse.quote(title)}"


def load_json(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def render_source_tags(sources: list, title_zh: str) -> str:
    tags = []
    has_free = False
    for src in sources:
        name = src.get("name", "")
        display = get_display_name(name)
        paid = is_paid(name)
        if not paid:
            has_free = True
            tags.append(f'<span class="src-tag src-free">{esc(display)}</span>')
        else:
            gurl = google_search_url(title_zh)
            tags.append(
                f'<a class="src-tag src-paid" href="{esc(gurl)}" '
                f'target="_blank" rel="noopener">{esc(display)}</a>'
            )
    if not has_free and tags:
        gurl = google_search_url(title_zh)
        tags.append(
            f'<a class="src-tag src-free" href="{esc(gurl)}" '
            f'target="_blank" rel="noopener">Google 搜索</a>'
        )
    return '<span class="src-sep">·</span>'.join(tags)


def render_headline(item: dict, rank: int) -> str:
    title = item.get("title_zh") or item.get("title", "")
    summary = item.get("summary_zh") or item.get("summary", "")
    image_url = item.get("image_url")
    sources = item.get("sources", [])

    img_html = ""
    if image_url:
        img_html = f'''
        <div class="hl-img">
            <img src="{esc(image_url)}" alt="" loading="lazy">
        </div>'''

    source_html = render_source_tags(sources, title)

    return f'''
    <article class="hl">
        {img_html}
        <div class="hl-body">
            <div class="hl-top">
                <span class="hl-num">{rank:02d}</span>
                <span class="hl-ai-badge">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
                    AI 摘要
                </span>
            </div>
            <h2 class="hl-title">{esc(title)}</h2>
            <div class="hl-ai-summary">
                <div class="ai-glow"></div>
                <div class="ai-summary-inner">
                    <span class="ai-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
                    </span>
                    <span class="ai-text">{esc(summary)}</span>
                </div>
            </div>
            <div class="hl-sources">{source_html}</div>
        </div>
    </article>'''


def render_ordinary(item: dict) -> str:
    title = item.get("title_zh") or item.get("title", "")
    summary = item.get("summary_zh") or item.get("summary", "")
    image_url = item.get("image_url")
    sources = item.get("sources", [])

    source_html = render_source_tags(sources, title)

    if image_url:
        return f'''
    <article class="ord">
        <div class="ord-img">
            <img src="{esc(image_url)}" alt="" loading="lazy">
        </div>
        <div class="ord-body">
            <h3 class="ord-title">{esc(title)}</h3>
            <div class="ord-summary">{esc(summary)}</div>
            <div class="ord-sources">{source_html}</div>
        </div>
    </article>'''
    else:
        return f'''
    <article class="ord">
        <div class="ord-body">
            <h3 class="ord-title">{esc(title)}</h3>
            <div class="ord-summary">{esc(summary)}</div>
            <div class="ord-sources">{source_html}</div>
        </div>
    </article>'''


def generate_html(headlines: list, ordinary: list, stats: dict) -> str:
    total_raw = stats.get("total_raw", 0)
    headline_count = len(headlines)
    ordinary_count = len(ordinary)

    today = datetime.now().strftime("%Y年%m月%d日")
    weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

    headlines_html = "\n".join(render_headline(h, i + 1) for i, h in enumerate(headlines))
    ordinary_html = "\n".join(render_ordinary(o) for o in ordinary)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日新闻简报 · {today}</title>
    <style>
        /* ==================== Design Tokens · DeepSeek 视觉增强 ==================== */
        :root {{
            --bg-body: #F4F6F9;
            --bg-card: rgba(255, 255, 255, 0.72);
            --bg-card-hover: rgba(255, 255, 255, 0.92);
            --bg-header: rgba(255, 255, 255, 0.65);

            --text-primary: #1E1E1E;
            --text-secondary: #4A4A4A;
            --text-tertiary: #8A8A8A;

            --border-light: rgba(220, 224, 230, 0.45);

            /* 多层阴影 + 彩色辉光 */
            --shadow-card:
                0 2px 8px rgba(15, 157, 138, 0.03),
                0 4px 20px rgba(0, 0, 0, 0.04),
                0 1px 4px rgba(0, 0, 0, 0.02);
            --shadow-card-hover:
                0 8px 32px rgba(15, 157, 138, 0.08),
                0 12px 48px rgba(0, 0, 0, 0.06),
                0 4px 12px rgba(255, 176, 124, 0.04);
            --shadow-glow-jade: 0 0 40px rgba(15, 157, 138, 0.12);
            --shadow-glow-apricot: 0 0 40px rgba(255, 176, 124, 0.10);

            --radius-card: 18px;
            --radius-sm: 10px;
            --radius-full: 9999px;

            /* 翡翠绿 → 青柠 渐变 */
            --green-jade: #0F9D8A;
            --green-jade-light: rgba(15, 157, 138, 0.10);
            --green-apple: #7CB342;
            --green-lime: #B5D33E;

            /* 暖色 */
            --coral: #FF6B6B;
            --coral-light: rgba(255, 107, 107, 0.12);
            --apricot: #FFB07C;
            --apricot-light: rgba(255, 176, 124, 0.15);

            /* 渐变 */
            --grad-brand: linear-gradient(135deg, #0F9D8A 0%, #7CB342 45%, #FFB07C 100%);
            --grad-ai: linear-gradient(135deg, rgba(15, 157, 138, 0.08) 0%, rgba(255, 176, 124, 0.10) 50%, rgba(181, 211, 62, 0.06) 100%);
            --grad-ai-glow: linear-gradient(135deg, rgba(15, 157, 138, 0.18) 0%, rgba(255, 176, 124, 0.15) 100%);
            --grad-card-surface: linear-gradient(180deg, rgba(255,255,255,0.9) 0%, rgba(255,255,255,0.6) 100%);

            --max-w: 720px;
            --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Noto Sans SC",
                     "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
        }}

        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ font-size: 16px; -webkit-font-smoothing: antialiased; }}

        body {{
            font-family: var(--font);
            background: var(--bg-body);
            color: var(--text-primary);
            line-height: 1.65;
            min-height: 100vh;
            position: relative;
            overflow-x: hidden;
        }}

        /* ==================== 背景光晕氛围 ==================== */
        body::before {{
            content: '';
            position: fixed;
            top: -20%;
            right: -10%;
            width: 600px;
            height: 600px;
            background: radial-gradient(circle, rgba(15, 157, 138, 0.06) 0%, transparent 70%);
            pointer-events: none;
            z-index: 0;
        }}
        body::after {{
            content: '';
            position: fixed;
            bottom: -15%;
            left: -10%;
            width: 500px;
            height: 500px;
            background: radial-gradient(circle, rgba(255, 176, 124, 0.05) 0%, transparent 70%);
            pointer-events: none;
            z-index: 0;
        }}

        /* ==================== Header · 玻璃 + 渐变品牌 ==================== */
        .site-header {{
            position: sticky;
            top: 0;
            z-index: 100;
            background: var(--bg-header);
            backdrop-filter: blur(20px) saturate(1.6);
            -webkit-backdrop-filter: blur(20px) saturate(1.6);
            border-bottom: 1px solid var(--border-light);
            box-shadow: 0 1px 24px rgba(0, 0, 0, 0.015);
        }}
        .header-inner {{
            max-width: var(--max-w);
            margin: 0 auto;
            padding: 0 24px;
            height: 60px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .header-brand {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header-icon {{
            width: 32px;
            height: 32px;
            border-radius: var(--radius-sm);
            background: var(--grad-brand);
            display: grid;
            place-items: center;
            box-shadow: 0 4px 16px rgba(15, 157, 138, 0.25);
        }}
        .header-icon svg {{ width: 17px; height: 17px; fill: #fff; }}
        .header-name {{
            font-size: 17px;
            font-weight: 700;
            letter-spacing: 0.2px;
            background: var(--grad-brand);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .header-meta {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .header-date {{
            font-size: 13px;
            color: var(--text-tertiary);
        }}
        .header-stats {{
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: var(--text-tertiary);
        }}
        .header-stats strong {{
            color: var(--text-primary);
            font-weight: 600;
        }}

        /* ==================== Container ==================== */
        .page {{
            max-width: var(--max-w);
            margin: 0 auto;
            padding: 0 24px;
            position: relative;
            z-index: 1;
        }}

        /* ==================== Section ==================== */
        .sec {{ padding: 32px 0 0; }}
        .sec-hd {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }}
        .sec-label {{
            font-size: 15px;
            font-weight: 600;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--text-secondary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .sec-badge {{
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.3px;
            padding: 3px 10px;
            border-radius: var(--radius-full);
        }}
        .badge-jade {{
            color: var(--green-jade);
            background: var(--green-jade-light);
            box-shadow: 0 0 12px rgba(15, 157, 138, 0.08);
        }}
        .badge-apricot {{
            color: var(--apricot);
            background: var(--apricot-light);
            box-shadow: 0 0 12px rgba(255, 176, 124, 0.08);
        }}
        .sec-line {{
            flex: 1;
            height: 1px;
            background: linear-gradient(90deg, var(--border-light), transparent);
        }}

        .divider {{
            max-width: var(--max-w);
            margin: 0 auto;
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--border-light) 20%, var(--border-light) 80%, transparent);
        }}

        /* ==================== Headlines · 渐变表面 + 辉光 ==================== */
        .hl-wrap {{ display: flex; flex-direction: column; gap: 16px; }}

        .hl {{
            background: var(--grad-card-surface);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-radius: var(--radius-card);
            box-shadow: var(--shadow-card);
            border: 1px solid rgba(255, 255, 255, 0.65);
            overflow: hidden;
            transition: box-shadow 0.35s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
        }}
        .hl::after {{
            content: '';
            position: absolute;
            inset: 0;
            border-radius: var(--radius-card);
            background: linear-gradient(135deg, rgba(15, 157, 138, 0.02) 0%, rgba(255, 176, 124, 0.02) 100%);
            pointer-events: none;
        }}
        .hl:hover {{
            box-shadow: var(--shadow-card-hover), var(--shadow-glow-jade);
            transform: translateY(-3px);
        }}

        .hl-img {{
            width: 100%;
            height: 180px;
            overflow: hidden;
            background: linear-gradient(135deg, #f0efed 0%, #e8e6e3 100%);
        }}
        .hl-img img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}

        .hl-body {{ padding: 18px 24px 20px; position: relative; z-index: 1; }}

        .hl-top {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }}
        .hl-num {{
            font-size: 12px;
            font-weight: 700;
            color: var(--green-jade);
            background: var(--green-jade-light);
            padding: 3px 10px;
            border-radius: var(--radius-sm);
            font-variant-numeric: tabular-nums;
            box-shadow: 0 0 8px rgba(15, 157, 138, 0.06);
        }}
        .hl-ai-badge {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-size: 11px;
            font-weight: 600;
            color: var(--apricot);
            background: var(--apricot-light);
            padding: 3px 10px;
            border-radius: var(--radius-full);
            box-shadow: 0 0 12px rgba(255, 176, 124, 0.08);
        }}
        .hl-ai-badge svg {{ width: 13px; height: 13px; }}

        .hl-title {{
            font-size: 18px;
            font-weight: 600;
            line-height: 1.45;
            color: var(--text-primary);
            margin-bottom: 12px;
            letter-spacing: -0.2px;
        }}

        /* ==================== AI Insight · 视觉重点 ==================== */
        .hl-ai-summary {{
            position: relative;
            margin-bottom: 14px;
            border-radius: var(--radius-sm);
            overflow: hidden;
        }}
        .ai-glow {{
            position: absolute;
            inset: -1px;
            border-radius: var(--radius-sm);
            background: var(--grad-ai-glow);
            opacity: 0.5;
            filter: blur(8px);
            z-index: 0;
        }}
        .ai-summary-inner {{
            position: relative;
            z-index: 1;
            background: var(--grad-ai);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.4);
            border-radius: var(--radius-sm);
            padding: 12px 16px;
            display: flex;
            gap: 10px;
            align-items: flex-start;
        }}
        .ai-icon {{
            flex-shrink: 0;
            width: 28px;
            height: 28px;
            border-radius: 8px;
            background: var(--grad-ai-glow);
            display: grid;
            place-items: center;
            color: var(--green-jade);
            box-shadow: 0 0 16px rgba(15, 157, 138, 0.12);
        }}
        .ai-icon svg {{ width: 15px; height: 15px; }}
        .ai-text {{
            font-size: 13.5px;
            line-height: 1.65;
            color: var(--text-secondary);
        }}

        .hl-sources {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
        }}

        /* ==================== Source Tags ==================== */
        .src-tag {{
            display: inline-flex;
            align-items: center;
            gap: 3px;
            font-size: 11px;
            font-weight: 500;
            padding: 3px 10px;
            border-radius: var(--radius-full);
            text-decoration: none;
            transition: all 0.2s;
        }}
        .src-free {{
            color: var(--text-secondary);
            background: rgba(240, 242, 245, 0.7);
            backdrop-filter: blur(4px);
        }}
        .src-free:hover {{
            background: rgba(240, 242, 245, 0.95);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        }}
        .src-paid {{
            color: var(--coral);
            background: var(--coral-light);
            border: 1px solid rgba(255, 107, 107, 0.12);
        }}
        .src-paid:hover {{
            background: rgba(255, 107, 107, 0.18);
            box-shadow: 0 2px 12px rgba(255, 107, 107, 0.10);
        }}
        .src-sep {{
            color: rgba(200, 204, 210, 0.5);
            font-size: 10px;
        }}

        /* ==================== Ordinary · 渐变表面 ==================== */
        .ord-wrap {{
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding-bottom: 48px;
        }}

        .ord {{
            background: var(--grad-card-surface);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: var(--radius-card);
            box-shadow: var(--shadow-card);
            border: 1px solid rgba(255, 255, 255, 0.6);
            overflow: hidden;
            display: flex;
            transition: box-shadow 0.3s, transform 0.25s;
            position: relative;
        }}
        .ord::after {{
            content: '';
            position: absolute;
            inset: 0;
            border-radius: var(--radius-card);
            background: linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 50%);
            pointer-events: none;
        }}
        .ord:hover {{
            box-shadow: var(--shadow-card-hover), var(--shadow-glow-apricot);
            transform: translateY(-2px);
        }}

        .ord-img {{
            flex-shrink: 0;
            width: 140px;
            background: linear-gradient(135deg, #f0efed, #e8e6e3);
            overflow: hidden;
        }}
        .ord-img img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}

        .ord-body {{
            flex: 1;
            min-width: 0;
            padding: 14px 18px;
            display: flex;
            flex-direction: column;
            position: relative;
            z-index: 1;
        }}

        .ord-title {{
            font-size: 14.5px;
            font-weight: 600;
            line-height: 1.45;
            color: var(--text-primary);
            margin-bottom: 4px;
        }}

        .ord-summary {{
            font-size: 12.5px;
            line-height: 1.65;
            color: var(--text-secondary);
            flex: 1;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}

        .ord-sources {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
            margin-top: 8px;
        }}

        /* ==================== Footer ==================== */
        .foot {{
            max-width: var(--max-w);
            margin: 0 auto;
            padding: 24px;
            text-align: center;
            font-size: 12px;
            color: var(--text-tertiary);
            border-top: 1px solid var(--border-light);
        }}

        /* ==================== Responsive ==================== */
        @media (max-width: 640px) {{
            .header-meta {{ gap: 10px; }}
            .header-date {{ display: none; }}
            .hl-img {{ height: 140px; }}
            .ord {{ flex-direction: column; }}
            .ord-img {{ width: 100%; height: 130px; }}
        }}

        /* ==================== Dark Mode ==================== */
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-body: #0F1114;
                --bg-card: rgba(26, 28, 32, 0.80);
                --bg-card-hover: rgba(32, 34, 38, 0.92);
                --bg-header: rgba(15, 17, 20, 0.85);
                --text-primary: #EAEAEA;
                --text-secondary: #A0A0A0;
                --text-tertiary: #606060;
                --border-light: rgba(60, 64, 70, 0.45);
                --shadow-card:
                    0 2px 8px rgba(15, 157, 138, 0.05),
                    0 4px 20px rgba(0, 0, 0, 0.18),
                    0 1px 4px rgba(0, 0, 0, 0.12);
                --shadow-card-hover:
                    0 8px 32px rgba(15, 157, 138, 0.10),
                    0 12px 48px rgba(0, 0, 0, 0.25),
                    0 4px 12px rgba(255, 176, 124, 0.05);
                --shadow-glow-jade: 0 0 50px rgba(15, 157, 138, 0.15);
                --shadow-glow-apricot: 0 0 50px rgba(255, 176, 124, 0.12);
                --grad-card-surface: linear-gradient(180deg, rgba(36,38,42,0.85) 0%, rgba(26,28,32,0.7) 100%);
            }}
            body::before {{
                background: radial-gradient(circle, rgba(15, 157, 138, 0.08) 0%, transparent 70%);
            }}
            body::after {{
                background: radial-gradient(circle, rgba(255, 176, 124, 0.06) 0%, transparent 70%);
            }}
            .hl-img, .ord-img {{ background: linear-gradient(135deg, #1e2024, #25272b); }}
            .src-free {{ background: rgba(60, 64, 70, 0.45); }}
            .src-free:hover {{ background: rgba(60, 64, 70, 0.65); }}
            .ai-summary-inner {{ background: linear-gradient(135deg, rgba(15,157,138,0.12) 0%, rgba(255,176,124,0.10) 100%); }}
        }}
    </style>
</head>
<body>

<header class="site-header">
    <div class="header-inner">
        <div class="header-brand">
            <div class="header-icon">
                <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            </div>
            <span class="header-name">每日新闻简报</span>
        </div>
        <div class="header-meta">
            <span class="header-date">{today} · {weekday}</span>
            <div class="header-stats">
                <span><strong>{total_raw}</strong> 抓取</span>
                <span><strong>{headline_count + ordinary_count}</strong> 精选</span>
            </div>
        </div>
    </div>
</header>

<main class="page">

    <div class="sec">
        <div class="sec-hd">
            <span class="sec-label">今日头条</span>
            <span class="sec-badge badge-jade">TOP {headline_count}</span>
            <span class="sec-line"></span>
        </div>
        <div class="hl-wrap">
            {headlines_html}
        </div>
    </div>

    <div class="divider" style="margin-top:32px"></div>

    <div class="sec">
        <div class="sec-hd">
            <span class="sec-label">其他重要新闻</span>
            <span class="sec-badge badge-apricot">{ordinary_count}</span>
            <span class="sec-line"></span>
        </div>
        <div class="ord-wrap">
            {ordinary_html}
        </div>
    </div>

</main>

<footer class="foot">每日新闻简报 · v0.2.1 · DeepSeek 视觉增强原型</footer>

</body>
</html>'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DeepSeek 视觉风格迁移生成器 v0.2.1")
    parser.add_argument("--selected", default=str(PROJECT_ROOT / "output" / "selected_news.json"))
    parser.add_argument("--raw", default=str(PROJECT_ROOT / "data" / "daily_run_raw.json"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--output", default=str(PROJECT_ROOT / "prototype" / "deepseek_style_migration_v2" / "newsletter.html"))
    args = parser.parse_args()

    headlines = []
    ordinary = []
    stats = {"total_raw": 0}

    if os.path.exists(args.selected):
        print(f"读取: {args.selected}")
        selected = load_json(args.selected)
        headlines = selected.get("headlines", [])
        ordinary = selected.get("ordinary", [])
        stats["total_raw"] = selected.get("total_raw", 0)
        print(f"  头条: {len(headlines)}, 普通: {len(ordinary)}")

    if os.path.exists(args.raw) and (len(headlines) + len(ordinary)) < args.limit:
        print(f"补充: {args.raw}")
        raw_items = load_json(args.raw)
        stats["total_raw"] = len(raw_items)
        existing_titles = {item.get("title", "") for item in headlines + ordinary}
        for item in raw_items:
            if len(ordinary) >= args.limit - len(headlines):
                break
            if item.get("title", "") not in existing_titles:
                ordinary.append(item)
                existing_titles.add(item.get("title", ""))
        print(f"  补充后: 头条 {len(headlines)}, 普通 {len(ordinary)}")

    total = len(headlines) + len(ordinary)
    if total > args.limit:
        ordinary = ordinary[:args.limit - len(headlines)]

    total = len(headlines) + len(ordinary)
    img_count = sum(1 for item in headlines + ordinary if item.get("image_url"))
    paid_count = sum(1 for item in headlines + ordinary
                      if any(is_paid(s.get("name", "")) for s in item.get("sources", [])))

    print(f"\n生成统计:")
    print(f"  总数: {total} (头条 {len(headlines)} + 普通 {len(ordinary)})")
    print(f"  有图片: {img_count}")
    print(f"  含付费来源: {paid_count}")

    html_content = generate_html(headlines, ordinary, stats)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)

    size_kb = os.path.getsize(args.output) / 1024
    print(f"\n输出: {args.output}")
    print(f"大小: {size_kb:.1f} KB")
    print("完成!")


if __name__ == "__main__":
    main()
