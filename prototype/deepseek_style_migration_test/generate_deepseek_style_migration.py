#!/usr/bin/env python3
"""
DeepSeek 视觉风格迁移生成器 v0.2.0

基于 v0.1.0 Newsletter 结构 + DeepSeek 视觉设计语言。
只迁移视觉 Token，不复制页面结构。

数据来源：
  - output/selected_news.json（主要）
  - data/daily_run_raw.json（补充）

用法：
  python prototype/deepseek_style_migration_test/generate_deepseek_style_migration.py
  python prototype/deepseek_style_migration_test/generate_deepseek_style_migration.py --limit 20
"""

import json
import os
import sys
import html as html_module
import urllib.parse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── 来源配置（与 source_strategy.yaml 保持一致）──
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
    "Bloomberg": "彭博社",
    "CNBC": "CNBC",
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
    encoded = urllib.parse.quote(title)
    return f"https://www.google.com/search?q={encoded}"


def load_json(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 渲染函数 ──

def render_source_tags(sources: list, title_zh: str) -> str:
    """渲染来源标签：免费源直接显示，付费源显示 Google 搜索链接"""
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
    """渲染头条卡片 — 无 group_members 版本"""
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
            </div>
            <h2 class="hl-title">{esc(title)}</h2>
            <div class="hl-summary">{esc(summary)}</div>
            <div class="hl-sources">{source_html}</div>
        </div>
    </article>'''


def render_ordinary(item: dict) -> str:
    """渲染普通新闻卡片"""
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
    """生成完整 HTML 页面"""

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
        /* ==================== Design Tokens · DeepSeek 视觉迁移 ==================== */
        :root {{
            /* 背景系统 — 暖灰 */
            --bg-body: #F4F6F9;
            --bg-card: rgba(255, 255, 255, 0.82);
            --bg-card-hover: rgba(255, 255, 255, 0.96);
            --bg-header: rgba(255, 255, 255, 0.72);

            /* 文字层级 */
            --text-primary: #1E1E1E;
            --text-secondary: #4A4A4A;
            --text-tertiary: #8A8A8A;

            /* 边框 */
            --border-light: rgba(220, 224, 230, 0.5);

            /* 多层柔和阴影 */
            --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.04), 0 1px 4px rgba(0, 0, 0, 0.03);
            --shadow-card-hover: 0 12px 48px rgba(0, 0, 0, 0.07), 0 4px 12px rgba(0, 0, 0, 0.03);
            --shadow-header: 0 1px 20px rgba(0, 0, 0, 0.01);

            /* 圆角 — 18px 大圆角 */
            --radius-card: 18px;
            --radius-sm: 10px;
            --radius-full: 9999px;

            /* 翡翠绿主色 */
            --green-jade: #0F9D8A;
            --green-jade-light: rgba(15, 157, 138, 0.10);
            --green-apple: #7CB342;

            /* 暖色点缀 */
            --coral: #FF6B6B;
            --coral-light: rgba(255, 107, 107, 0.12);
            --apricot: #FFB07C;
            --apricot-light: rgba(255, 176, 124, 0.15);

            /* 布局 */
            --max-w: 720px;
            --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Noto Sans SC",
                     "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
        }}

        /* ==================== Reset ==================== */
        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ font-size: 16px; -webkit-font-smoothing: antialiased; }}

        body {{
            font-family: var(--font);
            background: var(--bg-body);
            color: var(--text-primary);
            line-height: 1.65;
            min-height: 100vh;
        }}

        /* ==================== Header · 玻璃质感 ==================== */
        .site-header {{
            position: sticky;
            top: 0;
            z-index: 100;
            background: var(--bg-header);
            backdrop-filter: blur(16px) saturate(1.4);
            -webkit-backdrop-filter: blur(16px) saturate(1.4);
            border-bottom: 1px solid var(--border-light);
            box-shadow: var(--shadow-header);
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
            width: 30px;
            height: 30px;
            border-radius: var(--radius-sm);
            background: linear-gradient(135deg, var(--green-jade), #B5D33E);
            display: grid;
            place-items: center;
            box-shadow: 0 4px 12px rgba(15, 157, 138, 0.20);
        }}
        .header-icon svg {{ width: 16px; height: 16px; fill: #fff; }}
        .header-name {{
            font-size: 16px;
            font-weight: 700;
            letter-spacing: 0.2px;
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
        }}

        /* ==================== Section ==================== */
        .sec {{ padding: 32px 0 0; }}
        .sec-hd {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }}
        .sec-label {{ font-size: 15px; font-weight: 600; }}
        .sec-badge {{
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.3px;
            padding: 2px 8px;
            border-radius: var(--radius-sm);
        }}
        .badge-jade {{
            color: var(--green-jade);
            background: var(--green-jade-light);
        }}
        .badge-apricot {{
            color: var(--apricot);
            background: var(--apricot-light);
        }}
        .sec-line {{
            flex: 1;
            height: 1px;
            background: linear-gradient(90deg, var(--border-light), transparent);
        }}

        /* ==================== Divider ==================== */
        .divider {{
            max-width: var(--max-w);
            margin: 0 auto;
            height: 1px;
            background: var(--border-light);
        }}

        /* ==================== Headlines · 玻璃卡片 ==================== */
        .hl-wrap {{ display: flex; flex-direction: column; gap: 14px; }}

        .hl {{
            background: var(--bg-card);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border-radius: var(--radius-card);
            box-shadow: var(--shadow-card);
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-left: 5px solid var(--green-jade);
            overflow: hidden;
            transition: box-shadow 0.3s, transform 0.25s, background 0.3s;
            position: relative;
        }}
        .hl:hover {{
            box-shadow: var(--shadow-card-hover);
            transform: translateY(-2px);
            background: var(--bg-card-hover);
        }}

        .hl-img {{
            width: 100%;
            height: 180px;
            overflow: hidden;
            background: #f0efed;
        }}
        .hl-img img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        .hl-body {{ padding: 16px 22px 18px; }}

        .hl-top {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .hl-num {{
            font-size: 12px;
            font-weight: 700;
            color: var(--green-jade);
            background: var(--green-jade-light);
            padding: 2px 8px;
            border-radius: var(--radius-sm);
            font-variant-numeric: tabular-nums;
        }}

        .hl-title {{
            font-size: 17px;
            font-weight: 600;
            line-height: 1.45;
            color: var(--text-primary);
            margin-bottom: 8px;
            letter-spacing: -0.2px;
        }}

        .hl-summary {{
            font-size: 13.5px;
            line-height: 1.65;
            color: var(--text-secondary);
            margin-bottom: 12px;
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
            padding: 3px 8px;
            border-radius: var(--radius-sm);
            text-decoration: none;
            transition: background 0.15s;
        }}
        .src-free {{
            color: var(--text-secondary);
            background: rgba(240, 242, 245, 0.6);
        }}
        .src-free:hover {{ background: rgba(240, 242, 245, 0.9); }}
        .src-paid {{
            color: var(--coral);
            background: var(--coral-light);
            border: 1px solid rgba(255, 107, 107, 0.15);
        }}
        .src-paid:hover {{ background: rgba(255, 107, 107, 0.18); }}
        .src-sep {{
            color: rgba(200, 204, 210, 0.5);
            font-size: 10px;
        }}

        /* ==================== Ordinary · 玻璃卡片 ==================== */
        .ord-wrap {{
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding-bottom: 48px;
        }}

        .ord {{
            background: var(--bg-card);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border-radius: var(--radius-card);
            box-shadow: var(--shadow-card);
            border: 1px solid rgba(255, 255, 255, 0.6);
            overflow: hidden;
            display: flex;
            gap: 0;
            transition: box-shadow 0.3s, transform 0.25s, background 0.3s;
            position: relative;
        }}
        .ord::before {{
            content: '';
            position: absolute;
            left: 0;
            top: 8px;
            bottom: 8px;
            width: 3px;
            border-radius: 2px;
            background: var(--apricot);
            opacity: 0;
            transition: opacity 0.25s;
        }}
        .ord:hover {{
            box-shadow: var(--shadow-card-hover);
            transform: translateY(-1px);
            background: var(--bg-card-hover);
        }}
        .ord:hover::before {{ opacity: 0.7; }}

        .ord-img {{
            flex-shrink: 0;
            width: 140px;
            background: #f0efed;
            overflow: hidden;
        }}
        .ord-img img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        .ord-body {{
            flex: 1;
            min-width: 0;
            padding: 14px 18px;
            display: flex;
            flex-direction: column;
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
            margin-top: 6px;
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
                --bg-body: #121418;
                --bg-card: rgba(30, 32, 36, 0.85);
                --bg-card-hover: rgba(36, 38, 42, 0.95);
                --bg-header: rgba(18, 20, 24, 0.88);
                --text-primary: #E8E8E8;
                --text-secondary: #A0A0A0;
                --text-tertiary: #666;
                --border-light: rgba(60, 64, 70, 0.5);
                --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.15), 0 1px 4px rgba(0, 0, 0, 0.1);
                --shadow-card-hover: 0 12px 48px rgba(0, 0, 0, 0.25), 0 4px 12px rgba(0, 0, 0, 0.1);
            }}
            .hl-img, .ord-img {{ background: #252525; }}
            .src-free {{ background: rgba(60, 64, 70, 0.4); }}
            .src-free:hover {{ background: rgba(60, 64, 70, 0.6); }}
        }}
    </style>
</head>
<body>

<!-- ═══ HEADER ═══ -->
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

    <!-- ═══ HEADLINES ═══ -->
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

    <!-- ═══ ORDINARY ═══ -->
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

<footer class="foot">每日新闻简报 · v0.2.0 · DeepSeek 视觉风格迁移原型</footer>

</body>
</html>'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DeepSeek 视觉风格迁移生成器 v0.2.0")
    parser.add_argument("--selected", default=str(PROJECT_ROOT / "output" / "selected_news.json"))
    parser.add_argument("--raw", default=str(PROJECT_ROOT / "data" / "daily_run_raw.json"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--output", default=str(PROJECT_ROOT / "prototype" / "deepseek_style_migration_test" / "newsletter.html"))
    args = parser.parse_args()

    headlines = []
    ordinary = []
    stats = {"total_raw": 0}

    # 读取 selected_news（有翻译）
    if os.path.exists(args.selected):
        print(f"读取: {args.selected}")
        selected = load_json(args.selected)
        headlines = selected.get("headlines", [])
        ordinary = selected.get("ordinary", [])
        stats["total_raw"] = selected.get("total_raw", 0)
        print(f"  头条: {len(headlines)}, 普通: {len(ordinary)}")

    # 如果数据不足，从 raw_news 补充
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

    # 限制总数
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
