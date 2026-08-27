#!/usr/bin/env python3
"""
DeepSeek 主题 HTML 渲染器

读取 pipeline 输出 output/selected_news.json，使用 v4 DeepSeek 页面设计输出 HTML。
与 generate_real_html_v2.py（classic 主题）共享同一份新闻数据。

本脚本只做"数据 → HTML"的渲染，不包含任何新闻处理业务逻辑
（RSS、dedup、selection、translation 全部由 run.py pipeline 完成）。

图片规则（冻结，见 PROJECT_RULES.md 第 2 节）：
每条新闻只原样使用其自身 RSS 提供的 `image_url`，不做任何关键词/group 匹配；
没有 `image_url` 的新闻一律渲染占位图，绝不跨新闻复用图片。
来源标签沿用已有方案：免费/付费来源分类展示。

用法：
  python generate_deepseek_html.py
"""
import json
import os
import sys
import html as html_module
import urllib.parse
from pathlib import Path
from datetime import datetime


def load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def esc(text: str) -> str:
    return html_module.escape(str(text))


# ── 来源显示名（沿用已有方案）──
SOURCE_DISPLAY = {
    "Reuters": "路透社", "Associated Press": "美联社", "AFP": "法新社",
    "BBC": "BBC", "BBC World": "BBC 世界", "BBC Chinese": "BBC中文",
    "The Guardian": "卫报", "Guardian": "卫报",
    "Politico Europe": "Politico欧洲",
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

# ── 付费来源名单（沿用已有方案）──
PAID_SOURCES = {
    "Financial Times", "The Economist", "New York Times",
    "NYT Technology", "Washington Post", "Wall Street Journal",
    "Bloomberg", "日经",
    "FT", "NYT", "NYT Tech", "WSJ", "WaPo", "Economist",
}


def get_display_name(name: str) -> str:
    return SOURCE_DISPLAY.get(name, name)


def is_paid(name: str) -> bool:
    return name in PAID_SOURCES


def google_search_url(title: str) -> str:
    return f"https://www.google.com/search?q={urllib.parse.quote(title)}"


def render_source_tags(sources: list, title: str) -> str:
    """来源标签：明确显示【免费】/【付费】/【Google 搜索】三类，用不同配色区分

    - 免费来源：浅绿背景 + 绿色文字，锚点跳转到原始新闻 URL
    - 付费来源：浅红背景 + 红色文字，锚点跳转到 Google 搜索（站点受付费墙限制）
    - Google 搜索跳转（无免费原文 URL 时的兜底）：浅蓝背景 + 蓝色文字
    """
    tags = []
    has_free = False
    for src in sources:
        name = src.get("name", "")
        display = get_display_name(name)
        free_url = src.get("url", "")
        if not is_paid(name):
            has_free = True
            if free_url:
                tags.append(
                    f'<a class="src-tag src-free" href="{esc(free_url)}" '
                    f'target="_blank" rel="noopener">【免费】{esc(display)}</a>'
                )
            else:
                tags.append(f'<span class="src-tag src-free">【免费】{esc(display)}</span>')
        else:
            gurl = google_search_url(title)
            tags.append(
                f'<a class="src-tag src-paid" href="{esc(gurl)}" '
                f'target="_blank" rel="noopener">【付费】{esc(display)}</a>'
            )
    if not has_free and tags:
        gurl = google_search_url(title)
        tags.append(
            f'<a class="src-tag src-search" href="{esc(gurl)}" '
            f'target="_blank" rel="noopener">Google 搜索</a>'
        )
    return '<span class="src-sep">·</span>'.join(tags)


def render_headline(item: dict, rank: int) -> str:
    title = item.get("title_zh") or item.get("title", "")
    summary = item.get("summary_zh") or item.get("summary", "")
    sources = item.get("sources", [])
    # 头条：左图右文；图片只允许使用该新闻自身 RSS 图片；无图使用占位块
    img = item.get("image_url") or ""

    if img:
        media_html = f'''
        <div class="hl-img">
            <img src="{esc(img)}" alt="" loading="lazy">
        </div>'''
    else:
        media_html = f'''
        <a class="hl-ph" href="{esc(_primary_url(item))}" target="_blank" rel="noopener" title="{esc(title)}">
            <span class="hl-ph-title">{esc(title)}</span>
        </a>'''

    source_html = render_source_tags(sources, title)

    return f'''
    <article class="hl">
        {media_html}
        <div class="hl-body">
            <h2 class="hl-title">
                <span class="hl-num">{rank:02d}</span>
                <span class="hl-title-text">{esc(title)}</span>
            </h2>
            <div class="hl-summary-wrap">
                <div class="hl-summary">{esc(summary)}</div>
            </div>
            <div class="hl-sources">{source_html}</div>
        </div>
    </article>'''


def render_ordinary(item: dict, index: int = 0) -> str:
    title = item.get("title_zh") or item.get("title", "")
    summary = item.get("summary_zh") or item.get("summary", "")
    sources = item.get("sources", [])
    # 图片只允许使用该新闻自身 RSS 图片；无图则统一风格占位块
    img = item.get("image_url") or ""

    source_html = render_source_tags(sources, title)

    if img:
        return f'''
    <article class="ord">
        <div class="ord-img">
            <img src="{esc(img)}" alt="" loading="lazy">
        </div>
        <div class="ord-body">
            <h3 class="ord-title">{esc(title)}</h3>
            <div class="ord-summary">{esc(summary)}</div>
            <div class="ord-sources">{source_html}</div>
        </div>
    </article>'''
    else:
        # 无图新闻：统一风格的纯色标题占位块（与图片区域等高、同宽）
        return f'''
    <article class="ord ord-nimg">
        <a class="ord-img ord-ph idx-{index % 2}" href="{esc(_primary_url(item))}" target="_blank" rel="noopener" title="{esc(title)}">
            <span class="ord-ph-title">{esc(title)}</span>
        </a>
        <div class="ord-body">
            <h3 class="ord-title">{esc(title)}</h3>
            <div class="ord-summary">{esc(summary)}</div>
            <div class="ord-sources">{source_html}</div>
        </div>
    </article>'''


def _primary_url(item: dict) -> str:
    """取来源原文 URL（没有则返回空，anchor href 非空即可）"""
    sources = item.get("sources", [])
    if sources and sources[0].get("url"):
        return sources[0]["url"]
    return "#missing-url"


CSS_TEMPLATE = """/* ==================== Design Tokens · DeepSeek v0.4 ==================== */
:root {
    --bg-body: #F4F6F9;
    --bg-card: rgba(255, 255, 255, 0.72);
    --bg-card-hover: rgba(255, 255, 255, 0.92);
    --bg-header: rgba(255, 255, 255, 0.65);

    --text-primary: #1E1E1E;
    --text-secondary: #4A4A4A;
    --text-tertiary: #8A8A8A;

    --border-light: rgba(220, 224, 230, 0.45);

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

    --green-jade: #0F9D8A;
    --green-jade-light: rgba(15, 157, 138, 0.10);
    --green-apple: #7CB342;
    --green-lime: #B5D33E;
    --coral: #FF6B6B;
    --coral-light: rgba(255, 107, 107, 0.12);
    --apricot: #FFB07C;
    --apricot-light: rgba(255, 176, 124, 0.15);

    --grad-brand: linear-gradient(135deg, #0F9D8A 0%, #7CB342 45%, #FFB07C 100%);
    --grad-summary: linear-gradient(135deg, rgba(15,157,138,0.10) 0%, rgba(255,176,124,0.12) 100%);
    --grad-card-surface: linear-gradient(180deg, rgba(255,255,255,0.9) 0%, rgba(255,255,255,0.6) 100%);

    --max-w: 1200px;   /* 桌面端优先：充分利用屏幕宽度（原 720px），保留原视觉风格 */
    --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Noto Sans SC",
             "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
}

*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
html { font-size: 16px; -webkit-font-smoothing: antialiased; }

body {
    font-family: var(--font);
    background: var(--bg-body);
    color: var(--text-primary);
    line-height: 1.65;
    min-height: 100vh;
    position: relative;
    overflow-x: hidden;
}

/* ==================== 背景光晕 ==================== */
body::before {
    content: '';
    position: fixed;
    top: -20%;
    right: -10%;
    width: 600px;
    height: 600px;
    background: radial-gradient(circle, rgba(15, 157, 138, 0.06) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}
body::after {
    content: '';
    position: fixed;
    bottom: -15%;
    left: -10%;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(255, 176, 124, 0.05) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}

/* ==================== Header ==================== */
.site-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--bg-header);
    backdrop-filter: blur(20px) saturate(1.6);
    -webkit-backdrop-filter: blur(20px) saturate(1.6);
    border-bottom: 1px solid var(--border-light);
    box-shadow: 0 1px 24px rgba(0, 0, 0, 0.015);
}
.header-inner {
    max-width: var(--max-w);
    margin: 0 auto;
    padding: 0 24px;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.header-brand { display: flex; align-items: center; gap: 10px; }
.header-icon {
    width: 32px;
    height: 32px;
    border-radius: var(--radius-sm);
    background: var(--grad-brand);
    display: grid;
    place-items: center;
    box-shadow: 0 4px 16px rgba(15, 157, 138, 0.25);
}
.header-icon svg { width: 17px; height: 17px; fill: #fff; }
.header-name {
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 0.2px;
    background: var(--grad-brand);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.header-meta { display: flex; align-items: center; gap: 16px; }
.header-date { font-size: 13px; color: var(--text-tertiary); }
.header-stats { display: flex; gap: 12px; font-size: 12px; color: var(--text-tertiary); }
.header-stats strong { color: var(--text-primary); font-weight: 600; }

/* ==================== Container ==================== */
.page {
    max-width: var(--max-w);
    margin: 0 auto;
    padding: 0 24px;
    position: relative;
    z-index: 1;
}

/* ==================== Section ==================== */
.sec { padding: 32px 0 0; }
.sec-hd { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.sec-label { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.sec-badge {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
    padding: 3px 10px;
    border-radius: var(--radius-full);
}
.badge-jade {
    color: var(--green-jade);
    background: var(--green-jade-light);
    box-shadow: 0 0 12px rgba(15, 157, 138, 0.08);
}
.badge-apricot {
    color: var(--apricot);
    background: var(--apricot-light);
    box-shadow: 0 0 12px rgba(255, 176, 124, 0.08);
}
.sec-line { flex: 1; height: 1px; background: linear-gradient(90deg, var(--border-light), transparent); }

.divider {
    max-width: var(--max-w);
    margin: 0 auto;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--border-light) 20%, var(--border-light) 80%, transparent);
}

/* ==================== Headlines ==================== */
.hl-wrap { display: flex; flex-direction: column; gap: 16px; }

.hl {
    background: var(--grad-card-surface);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-card);
    border: 1px solid rgba(255, 255, 255, 0.65);
    overflow: hidden;
    transition: box-shadow 0.35s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    /* 头条：左图右文；单条宽度约占满整行（约两倍普通卡片宽度） */
    display: flex;
    flex-direction: row;
    align-items: stretch;
}
.hl::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: var(--radius-card);
    background: linear-gradient(135deg, rgba(15, 157, 138, 0.02) 0%, rgba(255, 176, 124, 0.02) 100%);
    pointer-events: none;
}
.hl:hover {
    box-shadow: var(--shadow-card-hover), var(--shadow-glow-jade);
    transform: translateY(-3px);
}

/* 头条左图（右文）；图片置于固定高度容器，object-fit:cover 裁剪，不撑高卡片 */
.hl-img {
    flex: 0 0 360px;
    width: 360px;
    height: 220px;            /* 固定图片区域高度 */
    overflow: hidden;
    background: linear-gradient(135deg, #f0efed 0%, #e8e6e3 100%);
}
.hl-img img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

/* 无图占位块（同固定高度，视觉与图片区对齐） */
.hl-ph {
    flex: 0 0 360px;
    width: 360px;
    height: 220px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 22px;
    text-decoration: none;
    background: var(--grad-brand);
    transition: opacity 0.25s;
}
.hl-ph:hover { opacity: 0.92; }
.hl-ph-title {
    color: #fff;
    font-size: 17px;
    font-weight: 600;
    line-height: 1.55;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-all;
}

.hl-body { flex: 1; min-width: 0; padding: 22px 28px 22px; position: relative; z-index: 1; }

.hl-title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 18px;
    font-weight: 600;
    line-height: 1.45;
    margin-bottom: 12px;
    letter-spacing: -0.2px;
    color: var(--text-primary);
}
.hl-num {
    font-size: 13px;
    font-weight: 700;
    color: var(--green-jade);
    background: var(--green-jade-light);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
    box-shadow: 0 0 8px rgba(15, 157, 138, 0.06);
}
.hl-title-text { color: var(--text-primary); }

.hl-summary-wrap {
    background: var(--grad-summary);
    border: 1px solid rgba(15, 157, 138, 0.08);
    border-radius: var(--radius-sm);
    padding: 12px 16px;
    margin-bottom: 14px;
    position: relative;
    overflow: hidden;
}
.hl-summary-wrap::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -30%;
    width: 120px;
    height: 120px;
    background: radial-gradient(circle, rgba(255, 176, 124, 0.08) 0%, transparent 70%);
    pointer-events: none;
}
.hl-summary {
    font-size: 13.5px;
    line-height: 1.65;
    color: var(--text-secondary);
    position: relative;
    z-index: 1;
}

.hl-sources { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

/* ==================== Source Tags ==================== */
.src-tag {
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    font-weight: 500;
    padding: 3px 10px;
    border-radius: var(--radius-full);
    text-decoration: none;
    transition: all 0.2s;
}
.src-free {
    color: #2E7D32;
    background: rgba(76, 175, 80, 0.12);
    border: 1px solid rgba(76, 175, 80, 0.22);
}
.src-free:hover {
    background: rgba(76, 175, 80, 0.20);
    box-shadow: 0 2px 8px rgba(76, 175, 80, 0.08);
}
.src-paid {
    color: var(--coral);
    background: var(--coral-light);
    border: 1px solid rgba(255, 107, 107, 0.12);
}
.src-paid:hover {
    background: rgba(255, 107, 107, 0.18);
    box-shadow: 0 2px 12px rgba(255, 107, 107, 0.10);
}
.src-search {
    color: #1565C0;
    background: rgba(33, 150, 243, 0.12);
    border: 1px solid rgba(33, 150, 243, 0.22);
}
.src-search:hover {
    background: rgba(33, 150, 243, 0.20);
    box-shadow: 0 2px 12px rgba(33, 150, 243, 0.10);
}
.src-sep { color: rgba(200, 204, 210, 0.5); font-size: 10px; }

/* ==================== Ordinary ==================== */
.ord-wrap {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    padding-bottom: 48px;
    align-items: stretch;
}

.ord {
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
}
.ord::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: var(--radius-card);
    background: linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 50%);
    pointer-events: none;
}
.ord:hover {
    box-shadow: var(--shadow-card-hover), var(--shadow-glow-apricot);
    transform: translateY(-2px);
}

.ord-img {
    flex-shrink: 0;
    width: 160px;
    aspect-ratio: 16 / 10;
    background: linear-gradient(135deg, #f0efed, #e8e6e3);
    overflow: hidden;
}
.ord-img img { width: 100%; height: 100%; object-fit: cover; display: block; }

/* 无图占位块：统一风格纯色标题占位（与图片区域等高同宽） */
.ord-ph {
    width: 160px;
    aspect-ratio: 16 / 10;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 12px;
    text-decoration: none;
    transition: all 0.25s;
}
.ord-ph.idx-0 {
    background: linear-gradient(135deg, var(--green-jade) 0%, var(--green-apple) 100%);
}
.ord-ph.idx-1 {
    background: linear-gradient(135deg, var(--apricot) 0%, var(--coral) 100%);
}
.ord-ph:hover { opacity: 0.92; }
.ord-ph-title {
    color: #fff;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.5;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-all;
}

.ord-body {
    flex: 1;
    min-width: 0;
    padding: 14px 18px;
    display: flex;
    flex-direction: column;
    position: relative;
    z-index: 1;
}

.ord-title {
    font-size: 14.5px;
    font-weight: 600;
    line-height: 1.45;
    margin-bottom: 4px;
    color: var(--text-primary);
}

.ord-summary {
    font-size: 12.5px;
    line-height: 1.65;
    color: var(--text-secondary);
    flex: 1;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.ord-sources { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 8px; }

/* ==================== Footer ==================== */
.foot {
    max-width: var(--max-w);
    margin: 0 auto;
    padding: 24px;
    text-align: center;
    font-size: 12px;
    color: var(--text-tertiary);
    border-top: 1px solid var(--border-light);
}

/* ==================== Responsive ==================== */
@media (max-width: 640px) {
    .header-meta { gap: 10px; }
    .header-date { display: none; }
    .hl { flex-direction: column; }
    .hl-img, .hl-ph { flex: none; width: 100%; height: auto; aspect-ratio: 16 / 8; }
    .ord-wrap { grid-template-columns: 1fr; }
    .ord { flex-direction: column; }
    .ord-img { width: 100%; aspect-ratio: 16 / 9; }
    .ord-ph { width: 100%; aspect-ratio: 16 / 9; }
}

/* ==================== Dark Mode ==================== */
@media (prefers-color-scheme: dark) {
    :root {
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
        --grad-summary: linear-gradient(135deg, rgba(15,157,138,0.15) 0%, rgba(255,176,124,0.12) 100%);
    }
    body::before { background: radial-gradient(circle, rgba(15, 157, 138, 0.08) 0%, transparent 70%); }
    body::after { background: radial-gradient(circle, rgba(255, 176, 124, 0.06) 0%, transparent 70%); }
    .hl-img, .ord-img { background: linear-gradient(135deg, #1e2024, #25272b); }
    .src-free { background: rgba(76, 175, 80, 0.18); color: #81C784; border-color: rgba(129, 199, 132, 0.25); }
    .src-free:hover { background: rgba(76, 175, 80, 0.28); }
    .src-search { background: rgba(33, 150, 243, 0.18); color: #64B5F6; border-color: rgba(100, 181, 246, 0.25); }
    .src-search:hover { background: rgba(33, 150, 243, 0.28); }
    .src-paid { background: rgba(255, 107, 107, 0.18); color: #FF8A80; border-color: rgba(255, 138, 128, 0.25); }
    .src-paid:hover { background: rgba(255, 107, 107, 0.28); }
}
"""


def generate_html(headlines: list, ordinary: list, total_raw: int) -> str:
    headline_count = len(headlines)
    ordinary_count = len(ordinary)
    today = datetime.now().strftime("%Y年%m月%d日")
    weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

    headlines_html = "\n".join(
        render_headline(h, i + 1) for i, h in enumerate(headlines)
    )
    ordinary_html = "\n".join(
        render_ordinary(o, index=i) for i, o in enumerate(ordinary)
    )

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日新闻简报 · {today}</title>
    <style>
    {CSS_TEMPLATE}
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
            <span class="sec-label">今天重要新闻</span>
            <span class="sec-badge badge-jade">{headline_count}</span>
            <span class="sec-line"></span>
        </div>
        <div class="hl-wrap">
        {headlines_html}
        </div>
    </div>

    <div class="divider" style="margin-top:32px"></div>

    <div class="sec">
        <div class="sec-hd">
            <span class="sec-label">今日普通新闻</span>
            <span class="sec-badge badge-apricot">{ordinary_count}</span>
            <span class="sec-line"></span>
        </div>
        <div class="ord-wrap">
        {ordinary_html}
        </div>
    </div>

</main>

<footer class="foot">每日新闻简报 · DeepSeek 主题</footer>

</body>
</html>'''


def render(
    pipeline_json: str,
    raw_path: str,
    output_path: str,
    verbose: bool = True,
) -> int:
    """从 pipeline 输出渲染 DeepSeek HTML（pipeline 与 CLI 共用的入口）

    Args:
        pipeline_json: selected_news.json 路径
        raw_path: raw 新闻 JSON 路径（仅用于 total_raw 统计兜底，不参与图片）
        output_path: 输出 HTML 路径
        verbose: 是否打印统计信息

    Returns:
        0 成功，1 失败
    """
    if not os.path.exists(pipeline_json):
        if verbose:
            print(f"未找到 pipeline 输出: {pipeline_json}", file=sys.stderr)
            print("请先运行: python run.py --load-raw data/daily_run_raw.json", file=sys.stderr)
        return 1

    selected = load_json(pipeline_json)
    headlines = selected.get("headlines", [])
    ordinary = selected.get("ordinary", [])
    total_raw = selected.get("total_raw", 0)

    if verbose:
        print(f"头条: {len(headlines)}, 普通: {len(ordinary)}")

    # raw 仅在 selected_news.json 缺 total_raw 时用于统计兜底（不参与图片）
    raw_items = []
    if os.path.exists(raw_path):
        raw_items = load_json(raw_path)
        if not total_raw:
            total_raw = len(raw_items)

    # 图片：原样使用每条新闻自身 image_url，不做任何跨新闻匹配
    img_with = sum(1 for it in headlines + ordinary if it.get("image_url"))
    total = len(headlines) + len(ordinary)
    if verbose:
        print(f"图片: {img_with}/{total} 条自带 RSS 图片，其余使用占位图")

    html = generate_html(headlines, ordinary, total_raw)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    if verbose:
        print(f"已生成: {output_path}")
        print(f"大小: {os.path.getsize(output_path) / 1024:.1f} KB")

    zh_count = sum(1 for h in headlines if any('\u4e00' <= c <= '\u9fff' for c in h.get("title_zh", "")))
    if verbose:
        print(f"头条中文标题: {zh_count}/{len(headlines)}")
        zh_count2 = sum(1 for o in ordinary if any('\u4e00' <= c <= '\u9fff' for c in o.get("title_zh", "")))
        print(f"普通中文标题: {zh_count2}/{len(ordinary)}")

    return 0


def main():
    project_root = Path(__file__).resolve().parent

    # 数据来源与 classic 主题完全一致：pipeline 输出
    pipeline_json = os.path.join(project_root, "output", "selected_news.json")
    raw_path = os.path.join(project_root, "data", "daily_run_raw.json")
    output_path = os.path.join(project_root, "prototype", "deepseek_style_output", "newsletter.html")

    return render(pipeline_json, raw_path, output_path, verbose=True)


if __name__ == "__main__":
    sys.exit(main())