#!/usr/bin/env python3
"""
生成真实数据 HTML 原型 v2
读取 test_pipeline_v2.py 的输出（selected_news.json）
修复：翻译时机、Google链接、访问标签、多来源展示
"""
import json
import os
import sys
import urllib.parse
from datetime import datetime


def load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


SOURCE_NAME_MAP = {
    "NYT Technology": "纽约时报科技版",
    "New York Times": "纽约时报",
    "Financial Times": "金融时报",
    "Bloomberg": "彭博社",
    "NHK World": "NHK",
    "BBC": "BBC",
    "BBC Chinese": "BBC中文",
    "NYT Chinese": "纽约时报中文网",
    "The Guardian": "卫报",
    "DW": "德国之声",
    "Al Jazeera": "半岛电视台",
    "Politico Europe": "Politico欧洲",
}

# 来源访问类型映射（基于 source_strategy.yaml）
SOURCE_ACCESS_MAP = {
    "New York Times": "paid", "NYT Technology": "paid",
    "Financial Times": "paid", "Bloomberg": "paid",
    "Washington Post": "paid", "Wall Street Journal": "paid",
    "The Economist": "paid", "日经": "paid",
    "The Guardian": "free", "BBC": "free", "BBC World": "free",
    "DW": "free", "Al Jazeera": "free",
    "Reuters": "free", "Associated Press": "free", "AFP": "free",
    "CNBC": "free", "NHK World": "free",
    "NYT Chinese": "free", "新华社": "free", "联合早报": "free",
}


def google_search_url(title: str) -> str:
    """Issue 2: 用原始标题生成 Google 搜索链接（URL编码）"""
    encoded = urllib.parse.quote(title)
    return f"https://www.google.com/search?q={encoded}"


def access_label_html(access_type: str) -> str:
    """Issue 3: 生成访问标签 HTML"""
    if access_type == "free":
        return '<span style="color:#27ae60;font-size:11px;">[免费]</span>'
    elif access_type == "paid":
        return '<span style="color:#e74c3c;font-size:11px;">[付费]</span>'
    else:
        # unknown 状态暂标为 [免费]（待核实）
        return '<span style="color:#27ae60;font-size:11px;">[免费]</span>'


def render_source_meta(item: dict) -> str:
    """渲染来源行：所有来源按权威性排列在同一行，各自标注[免费]/[付费]

    支持两种数据格式：
    1. Pipeline 格式：item["sources"] = [{"name": "BBC", "url": "..."}]
    2. Test pipeline 格式：item["all_items"] = [{"source": "BBC", "url": "..."}]
    """
    # 兼容两种格式
    all_items = item.get("all_items", [])
    sources_list = item.get("sources", [])

    seen_sources = set()
    source_links = []
    has_free = False

    # 优先使用 all_items 格式（test pipeline）
    if all_items:
        for gi in all_items:
            src_name = gi.get("source", "")
            if src_name in seen_sources:
                continue
            seen_sources.add(src_name)
            display = SOURCE_NAME_MAP.get(src_name, src_name)
            url = gi.get("url", "")
            access = SOURCE_ACCESS_MAP.get(src_name, "free")
            if access == "free":
                has_free = True
            label = "[免费]" if access == "free" else "[付费]"
            color = "#27ae60" if access == "free" else "#e74c3c"
            source_links.append(
                f'<a href="{url}" target="_blank" rel="noopener">{display}</a>'
                f'<span style="color:{color};font-size:11px;">{label}</span>'
            )
    # Pipeline 格式：sources 是 [{"name": "BBC", "url": "..."}]
    elif sources_list:
        for src in sources_list:
            src_name = src.get("name", "")
            if src_name in seen_sources:
                continue
            seen_sources.add(src_name)
            display = SOURCE_NAME_MAP.get(src_name, src_name)
            url = src.get("url", "")
            access = SOURCE_ACCESS_MAP.get(src_name, "free")
            if access == "free":
                has_free = True
            label = "[免费]" if access == "free" else "[付费]"
            color = "#27ae60" if access == "free" else "#e74c3c"
            source_links.append(
                f'<a href="{url}" target="_blank" rel="noopener">{display}</a>'
                f'<span style="color:{color};font-size:11px;">{label}</span>'
            )

    # 如果全部是付费来源，附加 Google 搜索链接
    if not has_free and source_links:
        title = item.get("title", "") or item.get("title_original", "")
        gurl = google_search_url(title)
        source_links.append(
            f'<a href="{gurl}" target="_blank" rel="noopener" style="color:#27ae60;">Google搜索</a>'
        )

    return " <span style='width:3px;height:3px;background:#888;border-radius:50%;display:inline-block;vertical-align:middle;'></span> ".join(source_links)


def render_headline(item: dict, rank: int) -> str:
    """渲染头条卡片

    使用 RSS 原始 summary 的翻译（summary_zh），
    不使用 LLM 生成的 what_happened / why_matters。
    对于 related group，展示所有成员来源。
    """
    title = item.get("title_zh", item.get("title", ""))
    summary = item.get("summary_zh", item.get("summary", ""))
    image_url = item.get("image_url")

    meta_html = render_source_meta(item)

    # 如果是 related group，展示其他成员（标题 + 摘要 + 来源）
    related_html = ""
    group_members = item.get("group_members", [])
    if group_members:
        related_items = []
        for m in group_members:
            m_title = m.get("title_zh") or m.get("title", "")
            m_summary = m.get("summary_zh") or m.get("summary", "")
            m_meta_html = render_source_meta(m)

            item_html = f'<li><span class="related-title">{m_title}</span>'
            if m_summary:
                item_html += f'<div class="related-summary">{m_summary}</div>'
            item_html += f'<div class="related-meta">{m_meta_html}</div>'
            item_html += '</li>'
            related_items.append(item_html)

        if related_items:
            related_html = f'''<div class="related-sources">
              <div class="related-label">相关报道：</div>
              <ul>{"".join(related_items)}</ul>
            </div>'''

    # 图片区域
    image_html = ""
    if image_url:
        image_html = f'<div class="headline-image"><img src="{image_url}" alt="{title}" loading="lazy"></div>'

    return f'''
    <div class="headline-card">
      <div class="rank">{rank}</div>
      {image_html}
      <div class="content">
        <h3>{title}</h3>
        <div class="summary">{summary}</div>
        <div class="meta">{meta_html}</div>
        {related_html}
      </div>
    </div>
    '''


def render_ordinary(item: dict) -> str:
    """渲染普通新闻"""
    title = item.get("title_zh", item.get("title", ""))
    summary = item.get("summary_zh", item.get("summary", ""))
    image_url = item.get("image_url")

    meta_html = render_source_meta(item)

    # 有图：左图右文布局；无图：纯文字布局
    if image_url:
        return f'''
        <div class="ordinary-item has-image">
          <div class="ordinary-thumb">
            <img src="{image_url}" alt="{title}" loading="lazy">
          </div>
          <div class="ordinary-text">
            <h4>{title}</h4>
            <div class="summary">{summary}</div>
            <div class="meta">{meta_html}</div>
          </div>
        </div>
        '''
    else:
        return f'''
        <div class="ordinary-item">
          <h4>{title}</h4>
          <div class="summary">{summary}</div>
          <div class="meta">{meta_html}</div>
        </div>
        '''


def main():
    # 优先读取 Pipeline 输出的 selected_news.json
    pipeline_json = os.path.join(os.path.dirname(__file__), "output", "selected_news.json")
    if os.path.exists(pipeline_json):
        data_dir = os.path.join(os.path.dirname(__file__), "output")
    else:
        # 回退到旧的 test_pipeline 目录
        data_dir = os.path.join(os.path.dirname(__file__), "data", "test_pipeline")
    selected = load_json(os.path.join(data_dir, "selected_news.json"))
    headlines = selected.get("headlines", [])
    ordinary = selected.get("ordinary", [])

    print(f"头条: {len(headlines)}, 普通: {len(ordinary)}")

    # 统计
    free_count = sum(1 for h in headlines if h.get("strategy", {}).get("strategy_type") == "free_primary")
    paid_count = len(headlines) - free_count

    today = datetime.now().strftime("%Y年%m月%d日")
    weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

    headlines_html = "\n".join(render_headline(h, i + 1) for i, h in enumerate(headlines))
    ordinary_html = "\n".join(render_ordinary(o) for o in ordinary)

    total_raw = selected.get("total_raw", 340)
    total_groups = selected.get("total_groups", 0)

    # 统计 headline 中的 group 数量
    headline_group_count = len(headlines)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日新闻简报 - {today}</title>
<style>
:root {{
  --bg: #fafaf9;
  --surface: #ffffff;
  --text-primary: #1a1a1a;
  --text-secondary: #555555;
  --text-tertiary: #888888;
  --accent: #c0392b;
  --accent-light: #e74c3c;
  --border: #e8e8e8;
  --border-light: #f0f0f0;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.08);
  --radius: 8px;
  --max-w: 860px;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Noto Sans SC", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text-primary);
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}}
.site-header {{
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 40px 24px 32px;
  text-align: center;
}}
.site-header h1 {{ font-size: 28px; font-weight: 700; letter-spacing: 2px; }}
.site-header .date {{ font-size: 15px; color: var(--text-secondary); margin-top: 6px; }}
.site-header .tagline {{ font-size: 13px; color: var(--text-tertiary); margin-top: 4px; }}
.site-header .stats {{
  font-size: 12px; color: var(--text-tertiary); margin-top: 8px;
  padding: 8px 16px; background: #f8f8f8; border-radius: 6px; display: inline-block;
}}
.container {{ max-width: var(--max-w); margin: 0 auto; padding: 0 24px; }}
.section-title {{
  font-size: 18px; font-weight: 600; padding: 32px 0 16px;
  border-bottom: 2px solid var(--accent); margin-bottom: 20px;
  display: flex; align-items: center; gap: 8px;
}}
.section-title .badge {{
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--accent); color: #fff; font-size: 12px;
  font-weight: 600; padding: 2px 8px; border-radius: 10px;
}}
.headlines {{ display: flex; flex-direction: column; gap: 16px; }}
.headline-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 24px 28px;
  box-shadow: var(--shadow-sm); position: relative;
}}
.headline-card:hover {{ box-shadow: var(--shadow-md); border-color: #d0d0d0; }}
.headline-card .rank {{
  position: absolute; top: 20px; left: -1px;
  background: var(--accent); color: #fff; font-size: 13px;
  font-weight: 700; padding: 4px 10px 4px 12px; border-radius: 0 6px 6px 0;
  z-index: 2;
}}
.headline-image {{
  margin: -24px -28px 16px -28px;
  overflow: hidden;
  border-radius: var(--radius) var(--radius) 0 0;
}}
.headline-image img {{
  width: 100%; height: auto; max-height: 320px;
  object-fit: cover; display: block;
}}
.headline-card .content {{ padding-left: 8px; }}
.headline-card h3 {{ font-size: 18px; font-weight: 600; line-height: 1.5; margin-bottom: 8px; }}
.headline-card .summary {{ font-size: 14.5px; color: var(--text-secondary); line-height: 1.75; margin-bottom: 12px; }}
.headline-card .meta {{
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--text-tertiary); flex-wrap: wrap;
}}
.headline-card .meta a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
.headline-card .meta a:hover {{ text-decoration: underline; }}
.headline-card .meta .dot {{ width: 3px; height: 3px; background: var(--text-tertiary); border-radius: 50%; }}
.related-sources {{ margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border-light); }}
.related-label {{ font-size: 12px; color: var(--text-tertiary); margin-bottom: 4px; }}
.related-sources ul {{ list-style: none; padding: 0; margin: 0; }}
.related-sources li {{ font-size: 13px; color: var(--text-secondary); line-height: 1.6; padding-left: 12px; position: relative; }}
.related-sources li::before {{ content: ""; position: absolute; left: 0; top: 8px; width: 4px; height: 4px; background: var(--text-tertiary); border-radius: 50%; }}
.related-title {{ font-size: 18px; font-weight: 600; line-height: 1.5; margin-bottom: 8px; }}
.related-summary {{ font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin: 4px 0; }}
.related-meta {{ font-size: 12px; color: var(--text-tertiary); }}
.related-meta a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
.related-meta a:hover {{ text-decoration: underline; }}
.ordinary-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 1px;
  background: var(--border-light); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
}}
.ordinary-item {{ background: var(--surface); padding: 18px 20px; border-radius: 8px; margin-bottom: 10px; }}
.ordinary-item:hover {{ background: #f9f9f8; }}
.ordinary-item.has-image {{
  display: flex; gap: 16px; align-items: flex-start;
}}
.ordinary-thumb {{
  flex-shrink: 0; width: 140px; height: 100px;
  border-radius: 6px; overflow: hidden; background: #f0f0f0;
}}
.ordinary-thumb img {{
  width: 100%; height: 100%; object-fit: cover; object-position: center; display: block;
}}
.ordinary-text {{ flex: 1; min-width: 0; }}
.ordinary-item h4 {{ font-size: 14.5px; font-weight: 600; line-height: 1.55; margin-bottom: 6px; }}
.ordinary-item .summary {{
  font-size: 13px; color: var(--text-secondary); line-height: 1.65;
  margin-bottom: 8px; display: -webkit-box;
  -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
}}
.ordinary-item .meta {{ font-size: 12px; color: var(--text-tertiary); }}
.ordinary-item .meta a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
.ordinary-item .meta a:hover {{ text-decoration: underline; }}
.site-footer {{ text-align: center; padding: 40px 24px; font-size: 13px; color: var(--text-tertiary); border-top: 1px solid var(--border); margin-top: 40px; }}
@media (max-width: 700px) {{
  .container {{ padding: 0 16px; }}
  .headline-card {{ padding: 18px 16px 18px 20px; }}
  .headline-card h3 {{ font-size: 16px; }}
  .related-title {{ font-size: 16px; }}
  .ordinary-grid {{ grid-template-columns: 1fr; }}
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #1a1a1a; --surface: #242424; --text-primary: #e8e8e8;
    --text-secondary: #aaaaaa; --text-tertiary: #777777;
    --accent: #e74c3c; --border: #333333; --border-light: #2a2a2a;
  }}
  .ordinary-item:hover {{ background: #2a2a2a; }}
}}
</style>
</head>
<body>
<header class="site-header">
  <h1>每日新闻简报</h1>
  <div class="date">{today} · {weekday}</div>
  <div class="tagline">真实数据测试版 v2 - 重要性评分 + 按需翻译</div>
  <div class="stats">
    共 {total_raw} 条新闻 · {total_groups} 组 · 展示 {headline_group_count} 条头条 + {len(ordinary)} 条普通
  </div>
</header>
<main class="container">
  <div class="section-title">今日头条 <span class="badge">{headline_group_count}</span></div>
  <div class="headlines">{headlines_html}</div>
  <div class="section-title" style="margin-top: 40px;">其他重要新闻 <span class="badge">{len(ordinary)}</span></div>
  <div class="ordinary-grid">{ordinary_html}</div>
</main>
<footer class="site-footer">每日新闻简报 · 真实数据测试版 v2</footer>
</body>
</html>'''

    output_path = os.path.join(os.path.dirname(__file__), "prototype", "test_real_data.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"已生成: {output_path}")
    print(f"大小: {os.path.getsize(output_path) / 1024:.1f} KB")

    # 检查翻译情况
    zh_count = sum(1 for h in headlines if any('\u4e00' <= c <= '\u9fff' for c in h.get("title_zh", "")))
    print(f"头条中文标题: {zh_count}/{len(headlines)}")
    zh_count2 = sum(1 for o in ordinary if any('\u4e00' <= c <= '\u9fff' for c in o.get("title_zh", "")))
    print(f"普通中文标题: {zh_count2}/{len(ordinary)}")


if __name__ == "__main__":
    sys.exit(main())
