"""
Markdown 简报格式化

负责将结构化数据转换为最终的 Markdown 文件。
来源和 URL 信息来自原始 NewsItem，不由 LLM 生成。

头条和普通新闻均使用 RSS 原始 summary（翻译后），
不使用 LLM 生成的 what_happened / why_matters。
"""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _format_single_news(item: dict, index: int) -> str:
    """格式化单条新闻为 Markdown

    来源列表中的每个条目都会渲染为独立的链接，
    确保所有真实来源都被展示。
    """
    lines = []

    # 标题（优先使用中文标题）
    title = item.get("title_zh") or item.get("title", "无标题")
    lines.append(f"### {index}. {title}")
    lines.append("")

    # 摘要（优先使用中文摘要，回退到原始摘要）
    summary = item.get("summary_zh") or item.get("summary", "")
    if summary:
        lines.append(f"**摘要：** {summary}")
        lines.append("")

    # 来源（多来源列表）
    sources = item.get("sources", [])
    if sources:
        source_parts = []
        for src in sources:
            name = src.get("name", "未知来源")
            url = src.get("url", "")
            if url:
                source_parts.append(f"[{name}]({url})")
            else:
                source_parts.append(name)
        lines.append(f"**来源：** {' | '.join(source_parts)}")
        lines.append("")

    return "\n".join(lines)


def format_newsletter(
    newsletter_data: list[dict],
    output_dir: str = "output",
    filename_template: str = "newsletter_YYYY-MM-DD.md",
    sections_config: list[dict] | None = None,
    date: str | None = None,
    headlines: list[dict] | None = None,
) -> str:
    """将结构化简报数据格式化为 Markdown 文件

    Args:
        newsletter_data: 普通新闻列表
        output_dir: 输出目录
        filename_template: 文件名模板
        sections_config: 分区配置（从 newsletter.yaml 读取）
        date: 指定日期（YYYY-MM-DD），默认今天
        headlines: 头版新闻列表（由 LLM 筛选，使用 RSS 摘要）

    Returns:
        生成的文件路径
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # 生成 Markdown
    lines = []
    lines.append(f"# 📰 今日新闻简报")
    lines.append(f"")
    lines.append(f"**日期：** {date}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    news_index = 0

    # ============================================================
    # 头版区域
    # ============================================================
    if headlines:
        lines.append(f"## 📰 今日头版")
        lines.append("")

        for item in headlines:
            news_index += 1
            lines.append(_format_single_news(item, news_index))

        lines.append("---")
        lines.append("")

    # ============================================================
    # 普通新闻区域（有多少显示多少，不限数量）
    # ============================================================
    if newsletter_data:
        lines.append(f"## 🔵 其他新闻")
        lines.append("")

        for item in newsletter_data:
            news_index += 1
            lines.append(_format_single_news(item, news_index))

        lines.append("---")
        lines.append("")

    # 末尾说明
    if news_index == 0:
        lines.append("*今天没有检索到重要新闻。*")
        lines.append("")
    else:
        lines.append(f"*共 {news_index} 条新闻 | 由私人新闻简报工具生成*")
        lines.append("")

    # 写入文件
    os.makedirs(output_dir, exist_ok=True)
    filename = filename_template.replace("YYYY-MM-DD", date)
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"简报已保存到 {filepath}")
    return filepath
