from __future__ import annotations

import html
import re
import urllib.parse
from datetime import date
from typing import Any

from .models import EventGroup, RankedEvent, SourceRef, Translation


def _safe_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _source_dict(source: SourceRef) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "name": source.name,
        "url": _safe_url(source.url),
        "access_type": source.access_type,
        "provider": source.provider,
    }


def build_newsletter_data(
    *,
    run_date: str,
    groups: list[EventGroup],
    rankings: list[RankedEvent],
    translations: list[Translation],
    headline_count: int,
    ordinary_count: int,
    backup_count: int,
    stats: dict[str, Any],
) -> dict[str, Any]:
    groups_by_id = {group.event_id: group for group in groups}
    translated = {item.item_id: item for item in translations}

    def make_entry(ranked: RankedEvent) -> dict[str, Any]:
        group = groups_by_id[ranked.event_id]
        leader = group.leader
        leader_translation = translated[leader.item_id]
        all_sources: dict[str, SourceRef] = {}
        for item in group.items:
            for source in item.sources:
                all_sources.setdefault(source.source_id, source)
        members = []
        for item in (group.items if group.group_type == "related" else []):
            if item.item_id == leader.item_id:
                continue
            item_translation = translated.get(item.item_id)
            if item_translation is None or not item_translation.title_zh.strip():
                continue
            members.append(
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "title_zh": item_translation.title_zh,
                    "summary_zh": item_translation.summary_zh,
                    "published_at": item.published_at,
                    "sources": [_source_dict(source) for source in item.sources],
                }
            )
        return {
            "event_id": group.event_id,
            "group_type": group.group_type,
            "leader_item_id": leader.item_id,
            "title": leader.title,
            "title_zh": leader_translation.title_zh,
            "summary_zh": leader_translation.summary_zh,
            "published_at": leader.published_at,
            "image_url": _safe_url(leader.image_url),
            "sources": [
                _source_dict(source)
                for source in (
                    [all_sources[key] for key in sorted(all_sources)]
                    if group.group_type == "exact_match"
                    else leader.sources
                )
            ],
            "group_members": members if group.group_type == "related" else [],
            "scores": {
                "importance": ranked.importance_score,
                "interest": ranked.interest_score,
                "confidence": ranked.confidence,
                "final": ranked.final_score,
            },
            "editor_reason": ranked.reason,
            "translation": {
                "title_provider": leader_translation.title_provider,
                "summary_provider": leader_translation.summary_provider,
            },
        }

    entries = [
        entry
        for row in rankings
        if row.event_id in groups_by_id
        for entry in [make_entry(row)]
        if not _is_non_news_entry(entry)
    ]
    headline_end = min(headline_count, len(entries))
    ordinary_end = min(headline_end + ordinary_count, len(entries))
    backup_end = min(ordinary_end + backup_count, len(entries))
    return {
        "schema_version": 1,
        "run_date": run_date,
        "headlines": entries[:headline_end],
        "ordinary": entries[headline_end:ordinary_end],
        "backup": entries[ordinary_end:backup_end],
        "stats": stats,
    }


def _markdown_source(source: dict[str, Any]) -> str:
    name = source["name"] + ("（付费）" if source["access_type"] == "paid" else "")
    return f"[{name}]({source['url']})" if source["url"] else name


def render_markdown(newsletter: dict[str, Any]) -> str:
    lines = [f"# 每日新闻简报 · {newsletter['run_date']}", ""]
    for title, key in (("头条", "headlines"), ("更多新闻", "ordinary")):
        lines.extend([f"## {title}", ""])
        for index, item in enumerate(newsletter[key], start=1):
            lines.append(f"### {index}. {item['title_zh']}")
            lines.append("")
            if item["summary_zh"]:
                lines.extend([item["summary_zh"], ""])
            sources = " · ".join(_markdown_source(source) for source in item["sources"])
            lines.extend(
                [
                    f"来源：{sources}",
                    "",
                ]
            )
            if item["group_members"]:
                lines.append("相关报道：")
                for member in item["group_members"]:
                    member_sources = " · ".join(
                        _markdown_source(source) for source in member["sources"]
                    )
                    lines.append(f"- {member['title_zh']}（{member_sources}）")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


SOURCE_DISPLAY = {
    "reuters": "路透社",
    "ap": "美联社",
    "associated-press": "美联社",
    "bbc": "BBC",
    "guardian": "卫报",
    "nytimes": "纽约时报",
    "nyt": "纽约时报",
    "washingtonpost": "华盛顿邮报",
    "bloomberg": "彭博社",
    "economist": "经济学人",
    "financialtimes": "金融时报",
    "ft": "金融时报",
    "wsj": "华尔街日报",
    "nikkei": "日经亚洲",
    "aljazeera": "半岛电视台",
    "al-jazeera": "半岛电视台",
    "dw": "德国之声",
}


def _display_source_name(source: dict[str, Any]) -> str:
    source_id = str(source.get("source_id", "")).lower()
    return SOURCE_DISPLAY.get(source_id, str(source.get("name") or source_id or "来源"))


def _google_search_url(title: str) -> str:
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": title})


def _source_href(source: dict[str, Any], title: str) -> str:
    del title
    return _safe_url(str(source.get("url") or ""))


def _primary_href(item: dict[str, Any]) -> str:
    for source in item.get("sources", []):
        href = _source_href(source, str(item.get("title") or item.get("title_zh") or ""))
        if href:
            return href
    return ""


def _html_sources(sources: list[dict[str, Any]], title: str) -> str:
    rendered = []
    for source in sources:
        name = html.escape(_display_source_name(source))
        is_paid = source.get("access_type") == "paid"
        css_class = "src-source src-paid" if is_paid else "src-source src-free"
        status = "付费" if is_paid else "免费"
        href = _source_href(source, title)
        if href:
            source_element = (
                f'<a class="{css_class}" href="{html.escape(href, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">{name}'
                f'<span class="src-status">{status}</span></a>'
            )
        else:
            source_element = (
                f'<span class="{css_class}">{name}'
                f'<span class="src-status">{status}</span></span>'
            )
        search_element = ""
        if is_paid:
            search_href = _google_search_url(title)
            search_element = (
                f'<a class="src-search" href="{html.escape(search_href, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">Google 搜索</a>'
            )
        rendered.append(f'<span class="src-group">{source_element}{search_element}</span>')
    return "".join(rendered)


NON_NEWS_TITLE_PATTERNS = [
    re.compile(
        r"^(?:bloomberg\s+)?this weekend(?:\s+\d{1,2}/\d{1,2}/\d{2,4})?$",
        re.IGNORECASE,
    )
]
NON_NEWS_REASON_MARKERS = (
    "not a reported event",
    "not a news event",
    "program listing",
    "programme listing",
)


def _is_non_news_entry(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "").strip()
    reason = str(item.get("editor_reason") or "").casefold()
    return any(pattern.search(title) for pattern in NON_NEWS_TITLE_PATTERNS) or any(
        marker in reason for marker in NON_NEWS_REASON_MARKERS
    )


def _html_group_members(item: dict[str, Any]) -> str:
    if item.get("group_type") != "related":
        return ""
    members = item.get("group_members", [])
    if not members:
        return ""
    rows = []
    for member in members:
        title = str(member.get("title_zh") or member.get("title") or "")
        summary = str(member.get("summary_zh") or "")
        href = _primary_href(member)
        escaped_title = html.escape(title)
        linked_title = (
            f'<a href="{html.escape(href, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer">{escaped_title}</a>'
            if href
            else escaped_title
        )
        summary_html = f'<p>{html.escape(summary)}</p>' if summary else ""
        rows.append(
            '<li class="gm-item">'
            f'<h4>{linked_title}</h4>{summary_html}'
            f'<div class="source-row">{_html_sources(member.get("sources", []), title)}</div>'
            "</li>"
        )
    return (
        '<div class="gm-wrap">'
        f'<div class="gm-heading"><span>相关报道</span><b>{len(members)}</b></div>'
        f'<ul class="gm-list">{"".join(rows)}</ul>'
        "</div>"
    )


def _main_sources(item: dict[str, Any]) -> list[dict[str, Any]]:
    sources = list(item.get("sources", []))
    if item.get("group_type") != "related":
        return sources
    member_sources = {
        (str(source.get("source_id") or ""), str(source.get("url") or ""))
        for member in item.get("group_members", [])
        for source in member.get("sources", [])
    }
    leader_sources = [
        source
        for source in sources
        if (str(source.get("source_id") or ""), str(source.get("url") or ""))
        not in member_sources
    ]
    return leader_sources or sources[:1]


def _linked_title(item: dict[str, Any], css_class: str = "") -> str:
    title = str(item.get("title_zh") or item.get("title") or "")
    escaped_title = html.escape(title)
    href = _primary_href(item)
    if not href:
        return escaped_title
    class_attr = f' class="{css_class}"' if css_class else ""
    return (
        f'<a{class_attr} href="{html.escape(href, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer">{escaped_title}</a>'
    )


def _image_or_placeholder(item: dict[str, Any], kind: str, alternate: bool = False) -> str:
    image_url = _safe_url(str(item.get("image_url") or ""))
    title = str(item.get("title_zh") or item.get("title") or "")
    href = _primary_href(item)
    tag = "a" if href else "div"
    href_attr = (
        f' href="{html.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer"'
        if href
        else ""
    )
    if image_url:
        return (
            f'<{tag} class="{kind}-media"{href_attr}>'
            f'<img src="{html.escape(image_url, quote=True)}" alt="{html.escape(title, quote=True)}" '
            'loading="lazy" decoding="async" referrerpolicy="no-referrer">'
            f'</{tag}>'
        )
    alternate_class = " ph-apricot" if alternate else ""
    return (
        f'<{tag} class="{kind}-media {kind}-placeholder{alternate_class}"{href_attr} '
        f'aria-label="{html.escape(title, quote=True)}"><span>{html.escape(title)}</span></{tag}>'
    )


def _html_headline(item: dict[str, Any], ordinal: int) -> str:
    title = str(item.get("title_zh") or item.get("title") or "")
    summary = str(item.get("summary_zh") or "")
    summary_html = f'<p class="hl-summary">{html.escape(summary)}</p>' if summary else ""
    return f"""
    <article class="hl-card">
      {_image_or_placeholder(item, "hl")}
      <div class="hl-body">
        <div class="rank-line"><span>{ordinal:02d}</span><i>HEADLINE</i></div>
        <h3>{_linked_title(item, "title-link")}</h3>
        {summary_html}
        <div class="source-row">{_html_sources(_main_sources(item), title)}</div>
        {_html_group_members(item)}
      </div>
    </article>"""


def _html_ordinary(item: dict[str, Any], ordinal: int) -> str:
    title = str(item.get("title_zh") or item.get("title") or "")
    summary = str(item.get("summary_zh") or "")
    summary_html = f'<p class="ord-summary">{html.escape(summary)}</p>' if summary else ""
    return f"""
    <article class="ord-card">
      {_image_or_placeholder(item, "ord", alternate=ordinal % 2 == 0)}
      <div class="ord-body">
        <div class="ord-rank">{ordinal:02d}</div>
        <h3>{_linked_title(item, "title-link")}</h3>
        {summary_html}
        <div class="source-row">{_html_sources(_main_sources(item), title)}</div>
        {_html_group_members(item)}
      </div>
    </article>"""


DEEPSEEK_CSS = """
:root {
  color-scheme: light dark;
  --bg-body: #f4f6f9;
  --bg-surface: rgba(255, 255, 255, 0.82);
  --bg-surface-strong: rgba(255, 255, 255, 0.94);
  --text-main: #17211f;
  --text-soft: #60706c;
  --line: rgba(24, 65, 58, 0.12);
  --green-jade: #0f9d8a;
  --green-deep: #087767;
  --green-apple: #7cb342;
  --apricot: #ffb07c;
  --coral: #ff6b6b;
  --orange: #f59e42;
  --blue: #3976d2;
  --grad-brand: linear-gradient(135deg, #0f9d8a 0%, #7cb342 45%, #ffb07c 100%);
  --shadow-sm: 0 8px 22px rgba(22, 62, 56, 0.08);
  --shadow-lg: 0 18px 45px rgba(22, 62, 56, 0.12);
  --radius: 18px;
  --max-w: 1200px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-width: 320px;
  background:
    radial-gradient(circle at 5% 3%, rgba(15, 157, 138, 0.14), transparent 26rem),
    radial-gradient(circle at 96% 17%, rgba(255, 176, 124, 0.18), transparent 28rem),
    var(--bg-body);
  color: var(--text-main);
  font-family: "Times New Roman", "Noto Serif SC", "Source Han Serif SC", "Songti SC", STSong, SimSun, serif;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 64px;
  border-bottom: 1px solid var(--line);
  background: rgba(244, 246, 249, 0.78);
  backdrop-filter: blur(18px) saturate(145%);
  -webkit-backdrop-filter: blur(18px) saturate(145%);
}
.topbar-inner {
  width: min(calc(100% - 32px), var(--max-w));
  height: 100%;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.brand { display: flex; align-items: center; gap: 11px; min-width: 0; }
.brand-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 12px;
  background: var(--grad-brand);
  box-shadow: 0 7px 18px rgba(15, 157, 138, 0.22);
}
.brand-icon svg { width: 22px; height: 22px; }
.brand-copy { display: flex; flex-direction: column; line-height: 1.12; }
.brand-copy strong { font-size: 15px; letter-spacing: .04em; }
.brand-copy span { color: var(--text-soft); font-size: 11px; letter-spacing: .09em; }
.top-meta { display: flex; align-items: center; gap: 10px; color: var(--text-soft); font-size: 13px; white-space: nowrap; }
.meta-pill { padding: 5px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--bg-surface); }
.page { width: min(calc(100% - 32px), var(--max-w)); margin: 0 auto; padding: 42px 0 64px; }
.intro { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 28px; align-items: end; padding: 12px 2px 34px; }
.kicker { margin: 0 0 8px; color: var(--green-deep); font-weight: 750; font-size: 12px; letter-spacing: .16em; text-transform: uppercase; }
.intro h1 { margin: 0; font-size: clamp(36px, 6vw, 68px); line-height: 1.08; letter-spacing: -.05em; }
.intro h1 span { background: var(--grad-brand); -webkit-background-clip: text; background-clip: text; color: transparent; }
.intro-note { max-width: 370px; margin: 14px 0 0; color: var(--text-soft); font-size: 15px; }
.date-card {
  min-width: 190px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  text-align: right;
}
.date-card span { display: block; color: var(--text-soft); font-size: 12px; letter-spacing: .12em; }
.date-card strong { display: block; margin-top: 3px; font-size: 21px; }
.section { margin-top: 26px; }
.section-head { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 0 2px 18px; }
.section-title { margin: 0; font-size: 26px; letter-spacing: -.03em; }
.section-title small { display: block; margin-bottom: 3px; color: var(--green-deep); font-size: 11px; letter-spacing: .15em; }
.section-count { color: var(--text-soft); font-size: 13px; }
.headline-list { display: grid; gap: 18px; }
.hl-card, .ord-card {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.hl-card:hover, .ord-card:hover { transform: translateY(-2px); border-color: rgba(15, 157, 138, .26); box-shadow: var(--shadow-lg); }
.hl-card { display: grid; grid-template-columns: 360px minmax(0, 1fr); min-height: 220px; }
.hl-media, .ord-media { position: relative; display: block; overflow: hidden; text-decoration: none; background: #dfe9e6; }
.hl-media { width: 360px; height: 220px; }
.hl-media img, .ord-media img { width: 100%; height: 100%; display: block; object-fit: cover; transition: transform .35s ease; }
.hl-card:hover .hl-media img, .ord-card:hover .ord-media img { transform: scale(1.025); }
.hl-placeholder, .ord-placeholder {
  padding: 24px;
  display: flex;
  align-items: flex-end;
  background: linear-gradient(145deg, rgba(15, 157, 138, .95), rgba(124, 179, 66, .86));
  color: white;
}
.ph-apricot { background: linear-gradient(145deg, #ed9462, #ffb07c 55%, #ffce95); }
.hl-placeholder::after, .ord-placeholder::after {
  content: "";
  position: absolute;
  width: 150px;
  height: 150px;
  right: -48px;
  top: -55px;
  border-radius: 50%;
  border: 28px solid rgba(255, 255, 255, .15);
}
.hl-placeholder span, .ord-placeholder span { position: relative; z-index: 1; font-weight: 750; line-height: 1.4; }
.hl-placeholder span { max-width: 270px; font-size: 21px; }
.hl-body { padding: 22px 26px 20px; min-width: 0; }
.rank-line { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.rank-line span, .ord-rank {
  display: inline-grid;
  place-items: center;
  min-width: 31px;
  height: 24px;
  padding: 0 7px;
  border-radius: 999px;
  background: var(--grad-brand);
  color: white;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}
.rank-line i { color: var(--green-deep); font-size: 10px; font-style: normal; font-weight: 800; letter-spacing: .13em; }
.hl-body h3, .ord-body h3 { margin: 0; line-height: 1.38; letter-spacing: -.018em; }
.hl-body h3 { font-size: 23px; }
.title-link { text-decoration: none; }
.title-link:hover { color: var(--green-deep); }
.hl-summary {
  margin: 12px 0 14px;
  padding: 11px 13px;
  border-left: 3px solid var(--green-jade);
  border-radius: 0 10px 10px 0;
  background: linear-gradient(90deg, rgba(15, 157, 138, .09), rgba(255, 176, 124, .07));
  color: #3f514d;
  font-size: 14px;
}
.source-row { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }
.src-group { display: inline-flex; align-items: center; gap: 5px; min-width: 0; }
.src-source, .src-search {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 25px;
  padding: 3px 9px;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 650;
  line-height: 1.25;
  text-decoration: none;
  background: rgba(255, 255, 255, .47);
}
.src-source:hover, .src-search:hover { background: rgba(255, 255, 255, .82); }
.src-free { color: var(--green-deep); }
.src-paid { color: #d84f50; }
.src-search { color: var(--blue); }
.src-status { padding-left: 4px; border-left: 1px solid currentColor; font-size: 9px; font-weight: 700; opacity: .86; }
.gm-wrap { margin-top: 15px; padding-top: 12px; border-top: 1px dashed var(--line); }
.gm-heading { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; color: var(--text-soft); font-size: 11px; font-weight: 750; letter-spacing: .06em; }
.gm-heading b { min-width: 19px; height: 19px; display: grid; place-items: center; border-radius: 50%; background: rgba(15, 157, 138, .12); color: var(--green-deep); font-size: 10px; }
.gm-list { margin: 0; padding: 0; list-style: none; display: grid; gap: 9px; }
.gm-item { padding: 9px 11px; border-radius: 10px; background: rgba(23, 33, 31, .035); }
.gm-item h4 { margin: 0; font-size: 13px; line-height: 1.45; }
.gm-item h4 a { text-decoration: none; }
.gm-item h4 a:hover { color: var(--green-deep); }
.gm-item p { margin: 5px 0 7px; color: var(--text-soft); font-size: 12px; line-height: 1.55; }
.gm-item .src-source, .gm-item .src-search { min-height: 21px; padding: 2px 7px; font-size: 10px; }
.ordinary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.ord-card { display: grid; grid-template-columns: 160px minmax(0, 1fr); height: 286px; min-height: 0; }
.ord-media { width: 160px; height: 286px; min-height: 0; }
.ord-placeholder { padding: 15px; }
.ord-placeholder span { font-size: 14px; }
.ord-body { position: relative; min-width: 0; height: 286px; padding: 17px 18px 16px; display: flex; flex-direction: column; overflow: hidden; }
.ord-rank {
  align-self: flex-start;
  width: 24px;
  min-width: 24px;
  height: 24px;
  margin-bottom: 7px;
  padding: 0;
  border-radius: 50%;
  font-size: 10px;
}
.ord-body h3 {
  display: -webkit-box;
  overflow: hidden;
  flex: 0 0 auto;
  font-size: 16px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.ord-summary {
  display: -webkit-box;
  overflow: hidden;
  margin: 8px 0 11px;
  color: var(--text-soft);
  font-size: 12.5px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.ord-card .source-row { gap: 5px; max-height: 50px; overflow: hidden; flex: 0 0 auto; }
.ord-card .src-group { gap: 3px; }
.ord-card .src-source, .ord-card .src-search { min-height: 22px; padding: 2px 7px; font-size: 10px; }
.ord-card .gm-wrap { margin-top: 8px; padding-top: 6px; max-height: 68px; overflow: hidden; flex: 0 0 auto; }
.ord-card .gm-heading { margin-bottom: 3px; }
.ord-card .gm-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; align-items: center; padding: 4px 6px; }
.ord-card .gm-item:nth-child(n+2), .ord-card .gm-item p { display: none; }
.ord-card .gm-item h4 { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 1; font-size: 11px; }
.ord-card .gm-item .source-row { flex-wrap: nowrap; max-width: 180px; max-height: 23px; overflow: hidden; }
.footer { margin-top: 46px; padding-top: 20px; border-top: 1px solid var(--line); display: flex; justify-content: space-between; gap: 20px; color: var(--text-soft); font-size: 12px; }
.footer strong { color: var(--green-deep); }
@media (max-width: 900px) {
  .ordinary-grid { grid-template-columns: 1fr; }
  .hl-card { grid-template-columns: 300px minmax(0, 1fr); }
  .hl-media { width: 300px; }
}
@media (max-width: 700px) {
  .topbar { height: 58px; }
  .topbar-inner, .page { width: min(calc(100% - 24px), var(--max-w)); }
  .top-date { display: none; }
  .meta-pill { padding: 4px 8px; font-size: 11px; }
  .page { padding-top: 26px; }
  .intro { grid-template-columns: 1fr; gap: 17px; padding-bottom: 22px; }
  .intro h1 { font-size: clamp(34px, 12vw, 50px); }
  .date-card { min-width: 0; text-align: left; }
  .hl-card { display: block; }
  .hl-media { width: 100%; height: auto; aspect-ratio: 16 / 9; }
  .hl-body { padding: 19px 18px 18px; }
  .hl-body h3 { font-size: 20px; }
  .section-title { font-size: 23px; }
  .ord-card { grid-template-columns: 124px minmax(0, 1fr); height: 286px; }
  .ord-media { width: 124px; height: 286px; }
}
@media (max-width: 480px) {
  .brand-copy span { display: none; }
  .top-meta .meta-pill:first-of-type { display: none; }
  .page { width: min(calc(100% - 18px), var(--max-w)); }
  .ord-card { display: block; height: 430px; }
  .ord-media { width: 100%; height: 170px; min-height: 0; aspect-ratio: auto; }
  .ord-body { height: 260px; padding: 15px 15px 16px; }
  .footer { display: block; }
  .footer span { display: block; margin-top: 6px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg-body: #101716;
    --bg-surface: rgba(24, 35, 33, .84);
    --bg-surface-strong: rgba(28, 40, 38, .95);
    --text-main: #edf6f3;
    --text-soft: #a6b8b4;
    --line: rgba(210, 235, 228, .12);
    --green-deep: #65d2bf;
    --shadow-sm: 0 10px 26px rgba(0, 0, 0, .22);
    --shadow-lg: 0 19px 48px rgba(0, 0, 0, .33);
  }
  body {
    background:
      radial-gradient(circle at 5% 3%, rgba(15, 157, 138, .17), transparent 26rem),
      radial-gradient(circle at 96% 17%, rgba(255, 176, 124, .11), transparent 28rem),
      var(--bg-body);
  }
  .topbar { background: rgba(16, 23, 22, .8); }
  .hl-summary { color: #c1d0cc; }
  .src-source, .src-search { background: rgba(255, 255, 255, .035); }
  .gm-item { background: rgba(255, 255, 255, .035); }
}
"""


def render_html(newsletter: dict[str, Any]) -> str:
    run_day = date.fromisoformat(newsletter["run_date"])
    weekdays = "一二三四五六日"
    readable_date = run_day.strftime("%Y年%m月%d日")
    weekday = f"星期{weekdays[run_day.weekday()]}"
    headlines = [
        item for item in newsletter.get("headlines", []) if not _is_non_news_entry(item)
    ]
    ordinary = [
        item for item in newsletter.get("ordinary", []) if not _is_non_news_entry(item)
    ]
    selected_count = len(headlines) + len(ordinary)
    raw_count = newsletter.get("stats", {}).get("fetch", {}).get("items", selected_count)
    headline_html = "".join(
        _html_headline(item, index) for index, item in enumerate(headlines, start=1)
    )
    ordinary_html = "".join(
        _html_ordinary(item, index) for index, item in enumerate(ordinary, start=1)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <meta name="description" content="{html.escape(readable_date, quote=True)}每日新闻简报">
  <title>每日新闻简报 · {html.escape(newsletter['run_date'])}</title>
  <style>{DEEPSEEK_CSS}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <div class="brand-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 5.5h14v11H9.2L5 19.5v-14Z" stroke="white" stroke-width="1.8" stroke-linejoin="round"/>
            <path d="M8 9h8M8 12.5h5.5" stroke="white" stroke-width="1.8" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="brand-copy"><strong>每日新闻简报</strong><span>PRIVATE DAILY BRIEF</span></div>
      </div>
      <div class="top-meta">
        <span class="top-date">{readable_date}</span>
        <span class="meta-pill">抓取 {raw_count}</span>
        <span class="meta-pill">精选 {selected_count}</span>
      </div>
    </div>
  </header>
  <main class="page">
    <section class="intro" aria-labelledby="page-title">
      <div>
        <p class="kicker">Curated Intelligence · Daily</p>
        <h1 id="page-title">今日<span>新闻简报</span></h1>
        <p class="intro-note">从多个可信来源汇总、去重并整理的重要新闻。点击标题或来源标签可阅读原始报道。</p>
      </div>
      <div class="date-card"><span>ISSUE DATE</span><strong>{readable_date}</strong><span>{weekday}</span></div>
    </section>
    <section class="section" aria-labelledby="headline-title">
      <div class="section-head">
        <h2 class="section-title" id="headline-title"><small>TOP STORIES</small>今日头条</h2>
        <span class="section-count">{len(headlines)} 条重点报道</span>
      </div>
      <div class="headline-list">{headline_html}</div>
    </section>
    <section class="section" aria-labelledby="ordinary-title">
      <div class="section-head">
        <h2 class="section-title" id="ordinary-title"><small>MORE STORIES</small>更多新闻</h2>
        <span class="section-count">{len(ordinary)} 条</span>
      </div>
      <div class="ordinary-grid">{ordinary_html}</div>
    </section>
    <footer class="footer">
      <strong>每日新闻简报 · DeepSeek 主题</strong>
      <span>自动化管线生成 · 翻译和摘要仅供参考，请以来源报道为准</span>
    </footer>
  </main>
</body>
</html>"""
