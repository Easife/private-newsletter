#!/usr/bin/env python3
"""
DeepSeek UI 迁移测试生成器

读取 pipeline 数据，使用 deepseek_html 模板的视觉风格生成 HTML。
不修改现有生产流程，仅用于 UI 实验。

用法:
    python prototype/generate_deepseek_ui_test.py
    python prototype/generate_deepseek_ui_test.py --data data/daily_run_raw.json --limit 30
"""

import json
import os
import sys
import html as html_module
from pathlib import Path

# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 付费来源名单 (from source_strategy.yaml) ──
PAID_SOURCES = {
    "Financial Times", "The Economist", "New York Times",
    "NYT Technology", "Washington Post", "Wall Street Journal",
    "Bloomberg", "日经",
    # 缩写名 (from test data / RSS)
    "FT", "NYT", "NYT Tech", "WSJ", "WaPo", "Economist",
}

# ── 来源中文名映射 ──
SOURCE_DISPLAY = {
    "Reuters": "路透社", "Associated Press": "美联社", "AFP": "法新社",
    "BBC": "BBC", "BBC World": "BBC 世界", "The Guardian": "卫报",
    "Financial Times": "金融时报", "FT": "金融时报",
    "The Economist": "经济学人", "Economist": "经济学人",
    "New York Times": "纽约时报", "NYT": "纽约时报",
    "NYT Technology": "纽约时报科技版", "NYT Tech": "纽约时报科技版",
    "Washington Post": "华盛顿邮报", "WaPo": "华盛顿邮报",
    "Wall Street Journal": "华尔街日报", "WSJ": "华尔街日报",
    "Bloomberg": "彭博社",
    "CNBC": "CNBC",
    "NHK World": "NHK", "日经": "日经新闻",
    "新华社": "新华社", "联合早报": "联合早报",
    "DW": "德国之声", "Al Jazeera": "半岛电视台",
    "NYT Chinese": "纽约时报中文网",
}


def esc(text: str) -> str:
    return html_module.escape(str(text))


def get_display_name(source_name: str) -> str:
    return SOURCE_DISPLAY.get(source_name, source_name)


def is_paid(source_name: str) -> bool:
    return source_name in PAID_SOURCES


def build_google_query(title: str, source_name: str) -> str:
    import urllib.parse
    query = f"{title} {source_name}"
    return f"https://www.google.com/search?q={urllib.parse.quote(query)}"


def load_raw_news(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_selected_news(filepath: str) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def render_source_tags(sources: list[dict], title: str) -> str:
    """渲染来源标签，付费源显示 Paywall + Google 搜索链接"""
    tags = []
    for src in sources:
        name = src.get("name", "")
        display = get_display_name(name)
        paid = is_paid(name)

        if paid:
            google_url = build_google_query(title, name)
            tags.append(
                f'<a class="src-tag src-paid" href="{esc(google_url)}" '
                f'target="_blank" rel="noopener">'
                f'🔒 {esc(display)}</a>'
            )
        else:
            tags.append(f'<span class="src-tag src-free">{esc(display)}</span>')

    return " ".join(tags)


def render_card(item: dict, index: int, is_headline: bool = False) -> str:
    """渲染单条新闻卡片"""
    title = item.get("title_zh") or item.get("title", "")
    summary = item.get("summary_zh") or item.get("summary", "")
    sources = item.get("sources", [])
    image_url = item.get("image_url")
    group_type = item.get("group_type", "")

    # 来源标签
    source_html = render_source_tags(sources, title)

    # 图片
    if image_url:
        img_html = f'<div class="card-image"><img src="{esc(image_url)}" alt="" loading="lazy"></div>'
    else:
        img_html = ""

    # 头条特殊处理：左侧绿色边框 + 编号
    if is_headline:
        card_class = "news-card cat-tech fade-in"
        num_badge = f'<span class="card-num">{index:02d}</span>'
    else:
        card_class = "news-card fade-in"
        num_badge = ""

    # 组类型标签
    group_badge = ""
    if group_type == "exact_match":
        group_badge = '<span class="group-badge">多源报道</span>'

    return f'''
    <div class="{card_class}">
        {img_html}
        <div class="card-body">
            <div class="card-top">
                {num_badge}
                {group_badge}
            </div>
            <div class="card-title">{esc(title)}</div>
            <div class="card-ai-summary">
                <span class="ai-icon">🤖</span>
                <span class="ai-text"><strong>AI 摘要</strong> · {esc(summary)}</span>
            </div>
            <div class="card-footer">
                <div class="cf-source">{source_html}</div>
            </div>
        </div>
    </div>'''


def generate_html(headlines: list[dict], ordinary: list[dict], stats: dict) -> str:
    """生成完整 HTML 页面"""

    total_raw = stats.get("total_raw", 0)
    total_groups = stats.get("total_groups", 0)
    headline_count = len(headlines)
    ordinary_count = len(ordinary)
    total_count = headline_count + ordinary_count

    # 渲染头条
    headlines_html = ""
    for i, item in enumerate(headlines, 1):
        headlines_html += render_card(item, i, is_headline=True)

    # 渲染普通新闻
    ordinary_html = ""
    for item in ordinary:
        ordinary_html += render_card(item, 0, is_headline=False)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 新闻简报 · DeepSeek UI Test</title>
    <style>
        /* ==================== CSS Variables · 暖色平衡 (from deepseek template) ==================== */
        :root {{
            --bg-body: #F4F6F9;
            --bg-card: rgba(255, 255, 255, 0.82);
            --bg-card-hover: rgba(255, 255, 255, 0.96);
            --bg-sidebar: rgba(255, 255, 255, 0.70);

            --text-primary: #1E1E1E;
            --text-secondary: #4A4A4A;
            --text-tertiary: #8A8A8A;

            --border-light: rgba(220, 224, 230, 0.5);
            --border-focus: #0F9D8A;

            --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.04), 0 1px 4px rgba(0, 0, 0, 0.03);
            --shadow-card-hover: 0 12px 48px rgba(0, 0, 0, 0.07), 0 4px 12px rgba(0, 0, 0, 0.03);

            --radius-card: 18px;
            --radius-sm: 10px;
            --radius-full: 9999px;

            --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;

            --green-jade: #0F9D8A;
            --green-jade-light: rgba(15, 157, 138, 0.10);
            --green-apple: #7CB342;
            --green-lime: #B5D33E;

            --coral: #FF6B6B;
            --coral-light: rgba(255, 107, 107, 0.12);
            --apricot: #FFB07C;
            --apricot-light: rgba(255, 176, 124, 0.15);
            --sunflower: #FFD93D;
            --sunflower-light: rgba(255, 217, 61, 0.18);

            --cat-tech: #0F9D8A;
            --cat-business: #FFB07C;
        }}

        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ font-size: 16px; -webkit-font-smoothing: antialiased; }}
        body {{
            font-family: var(--font);
            background: var(--bg-body);
            color: var(--text-primary);
            display: flex;
            min-height: 100vh;
            overflow: hidden;
        }}

        /* Scrollbar */
        ::-webkit-scrollbar {{ width: 4px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: rgba(200, 204, 210, 0.5); border-radius: var(--radius-full); }}

        /* ==================== Sidebar ==================== */
        .sidebar {{
            width: 240px; min-width: 240px;
            background: var(--bg-sidebar);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-right: 1px solid rgba(220, 224, 230, 0.3);
            padding: 28px 20px 32px;
            display: flex; flex-direction: column;
            height: 100vh; position: sticky; top: 0;
            overflow-y: auto; flex-shrink: 0;
            box-shadow: 0 0 40px rgba(0, 0, 0, 0.02);
        }}
        .sidebar-brand {{
            display: flex; align-items: center; gap: 10px;
            padding-bottom: 28px;
            border-bottom: 1px solid rgba(220, 224, 230, 0.3);
            margin-bottom: 24px;
        }}
        .sidebar-brand .brand-dot {{
            width: 34px; height: 34px; border-radius: var(--radius-sm);
            background: linear-gradient(135deg, var(--green-jade) 0%, var(--green-lime) 100%);
            display: flex; align-items: center; justify-content: center;
            color: #fff; font-weight: 600; font-size: 14px;
            box-shadow: 0 4px 12px rgba(15, 157, 138, 0.20);
        }}
        .sidebar-brand .brand-name {{ font-size: 18px; font-weight: 600; letter-spacing: -0.3px; }}
        .sidebar-brand .brand-name span {{ color: var(--green-jade); }}

        .sidebar-label {{
            font-size: 11px; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.6px; color: var(--text-tertiary);
            padding: 0 12px 10px;
        }}

        .nav-list {{ list-style: none; display: flex; flex-direction: column; gap: 3px; flex: 1; }}
        .nav-item {{
            display: flex; align-items: center; gap: 12px;
            padding: 8px 12px; border-radius: var(--radius-sm);
            font-size: 14px; font-weight: 450; color: var(--text-secondary);
            cursor: pointer; transition: background 0.2s, color 0.2s;
            user-select: none;
        }}
        .nav-item:hover {{ background: rgba(255, 255, 255, 0.5); color: var(--text-primary); }}
        .nav-item.active {{
            background: var(--green-jade-light); color: var(--green-jade);
            font-weight: 500; box-shadow: 0 0 0 1px rgba(15, 157, 138, 0.10);
        }}
        .nav-item .nav-icon {{ font-size: 16px; width: 24px; text-align: center; flex-shrink: 0; }}
        .nav-item .nav-badge {{
            margin-left: auto; font-size: 11px; font-weight: 500;
            color: var(--text-tertiary); background: rgba(240, 242, 245, 0.6);
            padding: 0 8px; border-radius: var(--radius-full);
            line-height: 18px; min-width: 20px; text-align: center;
        }}
        .nav-item.active .nav-badge {{ background: var(--green-jade); color: #fff; }}

        .sidebar-footer {{
            margin-top: auto; padding-top: 20px;
            border-top: 1px solid rgba(220, 224, 230, 0.3);
            display: flex; align-items: center; gap: 10px;
        }}
        .sidebar-footer .sf-avatar {{
            width: 34px; height: 34px; border-radius: 50%;
            background: linear-gradient(135deg, var(--apricot) 0%, var(--coral) 100%);
            color: #fff; display: flex; align-items: center; justify-content: center;
            font-weight: 500; font-size: 13px;
            box-shadow: 0 4px 12px rgba(255, 107, 107, 0.20);
        }}
        .sidebar-footer .sf-info {{ flex: 1; }}
        .sidebar-footer .sf-name {{ font-size: 13px; font-weight: 500; }}
        .sidebar-footer .sf-status {{
            font-size: 11px; color: var(--text-tertiary);
            display: flex; align-items: center; gap: 4px;
        }}
        .sidebar-footer .sf-status .dot {{
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--green-apple);
            animation: pulse-dot 2.4s ease-in-out infinite;
        }}
        @keyframes pulse-dot {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.8); }}
        }}

        /* ==================== Main ==================== */
        .main {{
            flex: 1; display: flex; flex-direction: column;
            height: 100vh; overflow: hidden; background: var(--bg-body);
        }}

        /* ==================== Topbar ==================== */
        .topbar {{
            background: rgba(255, 255, 255, 0.55);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid rgba(220, 224, 230, 0.3);
            padding: 0 40px; height: 64px;
            display: flex; align-items: center; justify-content: space-between;
            flex-shrink: 0;
            box-shadow: 0 1px 20px rgba(0, 0, 0, 0.01);
        }}
        .topbar-left {{ display: flex; align-items: center; gap: 16px; }}
        .topbar-left .page-title {{
            font-size: 16px; font-weight: 600; letter-spacing: -0.2px;
        }}
        .topbar-left .page-title .highlight {{ color: var(--green-jade); }}
        .topbar-left .page-title .warm-dot {{
            display: inline-block; width: 8px; height: 8px;
            border-radius: 50%; background: var(--apricot);
            margin-left: 6px;
            box-shadow: 0 0 12px rgba(255, 176, 124, 0.3);
        }}
        .topbar-right {{ display: flex; align-items: center; gap: 16px; }}
        .topbar-right .ai-status {{
            display: flex; align-items: center; gap: 6px;
            font-size: 12px; color: var(--text-tertiary);
            background: rgba(255, 255, 255, 0.5);
            padding: 4px 14px 4px 10px; border-radius: var(--radius-full);
            border: 1px solid rgba(220, 224, 230, 0.3);
        }}
        .topbar-right .ai-status .dot {{
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--green-apple);
            animation: pulse-dot 2.4s ease-in-out infinite;
        }}
        .topbar-right .avatar {{
            width: 34px; height: 34px; border-radius: 50%;
            background: linear-gradient(135deg, var(--apricot) 0%, var(--sunflower) 100%);
            color: #fff; display: flex; align-items: center; justify-content: center;
            font-weight: 500; font-size: 13px; cursor: pointer;
            box-shadow: 0 4px 12px rgba(255, 176, 124, 0.20);
        }}

        /* ==================== Content ==================== */
        .content {{
            flex: 1; overflow-y: auto; padding: 28px 40px 60px;
        }}
        .content-header {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 24px; padding-bottom: 12px;
            border-bottom: 1px solid rgba(220, 224, 230, 0.3);
        }}
        .content-header .ch-left {{ display: flex; align-items: baseline; gap: 12px; }}
        .content-header .ch-left h2 {{
            font-size: 22px; font-weight: 600; letter-spacing: -0.3px;
        }}
        .content-header .ch-left .ch-count {{ font-size: 13px; color: var(--text-tertiary); }}

        /* ==================== Section Divider ==================== */
        .section-divider {{
            display: flex; align-items: center; gap: 12px;
            margin: 28px 0 16px;
        }}
        .section-divider .sec-label {{
            font-size: 13px; font-weight: 600; color: var(--text-secondary);
            white-space: nowrap;
        }}
        .section-divider .sec-badge {{
            font-size: 11px; font-weight: 600; color: var(--green-jade);
            background: var(--green-jade-light);
            padding: 2px 8px; border-radius: var(--radius-full);
        }}
        .section-divider .sec-line {{
            flex: 1; height: 1px;
            background: linear-gradient(90deg, rgba(220, 224, 230, 0.5), transparent);
        }}

        /* ==================== Feed ==================== */
        .feed {{ display: flex; flex-direction: column; gap: 14px; }}

        /* ==================== News Card ==================== */
        .news-card {{
            background: var(--bg-card);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border-radius: var(--radius-card);
            box-shadow: var(--shadow-card);
            transition: box-shadow 0.3s, transform 0.25s, background 0.3s;
            cursor: default;
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-left: 5px solid transparent;
            overflow: hidden;
        }}
        .news-card:hover {{
            box-shadow: var(--shadow-card-hover);
            transform: translateY(-2px);
            background: var(--bg-card-hover);
            border-color: rgba(255, 255, 255, 0.9);
        }}
        .news-card.cat-tech {{ border-left-color: var(--cat-tech); }}
        .news-card.cat-business {{ border-left-color: var(--cat-business); }}

        /* Card image */
        .card-image {{
            width: 100%; height: 180px; overflow: hidden;
            background: #f0efed;
        }}
        .card-image img {{
            width: 100%; height: 100%; object-fit: cover; display: block;
        }}

        /* Card body */
        .card-body {{ padding: 16px 22px 18px; }}

        .card-top {{
            display: flex; align-items: center; gap: 8px;
            margin-bottom: 6px;
        }}
        .card-num {{
            font-size: 12px; font-weight: 700; color: var(--green-jade);
            background: var(--green-jade-light);
            padding: 2px 8px; border-radius: var(--radius-sm);
            font-variant-numeric: tabular-nums;
        }}
        .group-badge {{
            font-size: 10px; font-weight: 600; color: var(--apricot);
            background: var(--apricot-light);
            padding: 2px 8px; border-radius: var(--radius-full);
            letter-spacing: 0.3px;
        }}

        .card-title {{
            font-size: 17px; font-weight: 600; line-height: 1.45;
            color: var(--text-primary); margin-bottom: 8px;
            letter-spacing: -0.2px;
        }}

        /* AI Summary */
        .card-ai-summary {{
            background: linear-gradient(135deg, var(--green-jade-light) 0%, var(--apricot-light) 100%);
            border-radius: var(--radius-sm);
            padding: 10px 14px; margin-bottom: 12px;
            display: flex; gap: 10px; align-items: flex-start;
            border: 1px solid rgba(255, 255, 255, 0.3);
            backdrop-filter: blur(4px);
        }}
        .card-ai-summary .ai-icon {{ font-size: 16px; flex-shrink: 0; margin-top: 1px; }}
        .card-ai-summary .ai-text {{
            font-size: 13.5px; line-height: 1.6; color: var(--text-secondary);
        }}
        .card-ai-summary .ai-text strong {{ color: var(--green-jade); font-weight: 500; }}

        /* Card footer / source tags */
        .card-footer {{
            display: flex; justify-content: space-between; align-items: center;
            font-size: 12px; color: var(--text-tertiary);
            flex-wrap: wrap; gap: 6px;
        }}
        .cf-source {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}

        .src-tag {{
            display: inline-flex; align-items: center; gap: 3px;
            font-size: 11px; font-weight: 500;
            padding: 3px 8px; border-radius: var(--radius-sm);
            text-decoration: none; transition: background 0.15s;
        }}
        .src-free {{
            color: var(--text-secondary);
            background: rgba(240, 242, 245, 0.6);
        }}
        .src-paid {{
            color: var(--coral);
            background: var(--coral-light);
            border: 1px solid rgba(255, 107, 107, 0.15);
        }}
        .src-paid:hover {{
            background: rgba(255, 107, 107, 0.18);
        }}

        /* ==================== Animations ==================== */
        .fade-in {{ animation: fadeIn 0.45s ease forwards; }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        /* ==================== Responsive ==================== */
        @media (max-width: 820px) {{
            .sidebar {{
                width: 64px; min-width: 64px; padding: 20px 12px;
            }}
            .sidebar-brand .brand-name, .sidebar-label,
            .nav-item .nav-label, .nav-item .nav-badge,
            .sidebar-footer .sf-info {{ display: none; }}
            .sidebar-brand {{ padding-bottom: 16px; margin-bottom: 16px; justify-content: center; }}
            .sidebar-brand .brand-dot {{ width: 30px; height: 30px; font-size: 12px; }}
            .nav-item {{ justify-content: center; padding: 10px; }}
            .nav-item .nav-icon {{ font-size: 18px; width: auto; }}
            .sidebar-footer {{ justify-content: center; }}
            .sidebar-footer .sf-avatar {{ width: 30px; height: 30px; font-size: 11px; }}
            .topbar {{ padding: 0 20px; }}
            .content {{ padding: 20px 20px 40px; }}
            .topbar-right .ai-status {{ display: none; }}
            .card-title {{ font-size: 15px; }}
            .content-header .ch-left h2 {{ font-size: 18px; }}
        }}
        @media (max-width: 540px) {{
            .sidebar {{ display: none; }}
            .topbar {{ padding: 0 16px; height: 56px; }}
            .content {{ padding: 16px 16px 32px; }}
            .news-card {{ padding: 0; }}
            .card-body {{ padding: 14px 16px; }}
            .card-ai-summary {{ padding: 8px 12px; }}
            .card-ai-summary .ai-text {{ font-size: 12.5px; }}
            .content-header {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
            .card-image {{ height: 140px; }}
        }}

        /* ==================== Dark Mode ==================== */
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-body: #121418;
                --bg-card: rgba(30, 32, 36, 0.85);
                --bg-card-hover: rgba(36, 38, 42, 0.95);
                --bg-sidebar: rgba(24, 26, 30, 0.80);
                --text-primary: #E8E8E8;
                --text-secondary: #A0A0A0;
                --text-tertiary: #666;
                --border-light: rgba(60, 64, 70, 0.5);
                --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.15), 0 1px 4px rgba(0, 0, 0, 0.1);
                --shadow-card-hover: 0 12px 48px rgba(0, 0, 0, 0.25), 0 4px 12px rgba(0, 0, 0, 0.1);
            }}
            .sidebar {{ box-shadow: 0 0 40px rgba(0, 0, 0, 0.1); }}
            .topbar {{ box-shadow: 0 1px 20px rgba(0, 0, 0, 0.08); }}
            .card-image {{ background: #252525; }}
            .src-free {{ background: rgba(60, 64, 70, 0.4); }}
        }}
    </style>
</head>
<body>

    <!-- ==================== SIDEBAR ==================== -->
    <aside class="sidebar">
        <div class="sidebar-brand">
            <div class="brand-dot">N</div>
            <span class="brand-name">News <span>AI</span></span>
        </div>

        <div class="sidebar-label">新闻简报</div>
        <ul class="nav-list">
            <li class="nav-item active">
                <span class="nav-icon">📰</span>
                <span class="nav-label">全部新闻</span>
                <span class="nav-badge">{total_count}</span>
            </li>
            <li class="nav-item">
                <span class="nav-icon">⭐</span>
                <span class="nav-label">今日头条</span>
                <span class="nav-badge">{headline_count}</span>
            </li>
            <li class="nav-item">
                <span class="nav-icon">📋</span>
                <span class="nav-label">其他新闻</span>
                <span class="nav-badge">{ordinary_count}</span>
            </li>
        </ul>

        <div class="sidebar-footer">
            <div class="sf-avatar">AI</div>
            <div class="sf-info">
                <div class="sf-name">AI 新闻助手</div>
                <div class="sf-status"><span class="dot"></span> AI 在线</div>
            </div>
        </div>
    </aside>

    <!-- ==================== MAIN ==================== -->
    <main class="main">
        <header class="topbar">
            <div class="topbar-left">
                <span class="page-title">
                    今日 <span class="highlight">简报</span>
                    <span class="warm-dot"></span>
                </span>
            </div>
            <div class="topbar-right">
                <div class="ai-status">
                    <span class="dot"></span>
                    <span>AI 就绪</span>
                </div>
                <div class="avatar">AI</div>
            </div>
        </header>

        <section class="content">
            <div class="content-header">
                <div class="ch-left">
                    <h2>每日新闻简报</h2>
                    <span class="ch-count">{total_raw} 条抓取 → {total_count} 条精选</span>
                </div>
            </div>

            <!-- HEADLINES -->
            <div class="section-divider">
                <span class="sec-label">今日头条</span>
                <span class="sec-badge">{headline_count}</span>
                <span class="sec-line"></span>
            </div>
            <div class="feed">
                {headlines_html}
            </div>

            <!-- ORDINARY -->
            <div class="section-divider">
                <span class="sec-label">其他重要新闻</span>
                <span class="sec-badge">{ordinary_count}</span>
                <span class="sec-line"></span>
            </div>
            <div class="feed">
                {ordinary_html}
            </div>

        </section>
    </main>

</body>
</html>'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DeepSeek UI 迁移测试生成器")
    parser.add_argument("--data", default=str(PROJECT_ROOT / "data" / "daily_run_raw.json"),
                        help="原始新闻 JSON 文件路径")
    parser.add_argument("--selected", default=str(PROJECT_ROOT / "output" / "selected_news.json"),
                        help="已处理新闻 JSON 文件路径")
    parser.add_argument("--limit", type=int, default=30,
                        help="最多显示新闻条数 (默认 30)")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "prototype" / "deepseek_ui_test" / "newsletter_test.html"),
                        help="输出 HTML 文件路径")
    args = parser.parse_args()

    # 读取数据：优先使用 selected_news（有翻译），否则用 raw_news
    headlines = []
    ordinary = []
    stats = {"total_raw": 0, "total_groups": 0}

    if os.path.exists(args.selected):
        print(f"读取已处理数据: {args.selected}")
        selected = load_selected_news(args.selected)
        headlines = selected.get("headlines", [])
        ordinary = selected.get("ordinary", [])
        stats["total_raw"] = selected.get("total_raw", 0)
        stats["total_groups"] = selected.get("total_groups", 0)
        print(f"  头条: {len(headlines)}, 普通: {len(ordinary)}")
    else:
        print(f"已处理数据不存在，使用原始数据: {args.data}")

    # 如果 selected 数据不够，从 raw_news 补充
    if os.path.exists(args.data) and (len(headlines) + len(ordinary)) < args.limit:
        print(f"读取原始数据: {args.data}")
        raw_items = load_raw_news(args.data)
        stats["total_raw"] = len(raw_items)
        stats["total_groups"] = len(raw_items)

        # 从 raw_news 补充普通新闻
        needed = args.limit - len(headlines) - len(ordinary)
        existing_titles = {item.get("title", "") for item in headlines + ordinary}
        for item in raw_items:
            if len(ordinary) >= args.limit - len(headlines):
                break
            if item.get("title", "") not in existing_titles:
                ordinary.append(item)
                existing_titles.add(item.get("title", ""))

        print(f"  补充后: 头条 {len(headlines)}, 普通 {len(ordinary)}")

    # 限制总数
    total = len(headlines) + len(ordinary)
    if total > args.limit:
        ordinary = ordinary[:args.limit - len(headlines)]

    total = len(headlines) + len(ordinary)
    print(f"\n生成统计:")
    print(f"  总新闻数: {total}")
    print(f"  今日头条: {len(headlines)}")
    print(f"  普通新闻: {len(ordinary)}")

    # 统计图片
    img_count = sum(1 for item in headlines + ordinary if item.get("image_url"))
    print(f"  有图片: {img_count}")

    # 统计付费来源
    paid_count = 0
    for item in headlines + ordinary:
        for src in item.get("sources", []):
            if is_paid(src.get("name", "")):
                paid_count += 1
                break
    print(f"  付费来源: {paid_count}")

    # 生成 HTML
    html_content = generate_html(headlines, ordinary, stats)

    # 输出
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n输出文件: {args.output}")
    print("完成!")


if __name__ == "__main__":
    main()
