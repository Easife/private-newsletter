"""
非新闻内容过滤（公共模块）

main.py 和 test_pipeline_v2.py 共用此模块，
避免维护两套过滤规则。

规则覆盖 NEWSLETTER_RULES.md §7.3 中已确定的非新闻类型：
- 征集/互动
- 订阅/推广
- 播客/视频推广
- 产品介绍/评测
- 纯评论/互动邀请
- 编辑/预告
- 指南/解释型内容（guide, explainer, Q&A）
"""

import re


NON_NEWS_PATTERNS = [
    # 征集/互动
    r"send us your", r"ask us", r"your questions", r"tell us",
    r"share your", r"write to us", r"submit", r"call for",
    r"ask readers", r"reader question",
    # 订阅/推广
    r"subscribe", r"newsletter signup", r"sign up for",
    r"try .* free", r"premium access", r"membership",
    r"sponsored", r"advertisement", r"partner content",
    # 播客/视频推广
    r"podcast", r"listen to", r"watch our", r"video series",
    r"episode \d+", r"new episode", r"latest episode",
    r"season \d+", r"series premiere",
    # 产品介绍/评测
    r"review:", r"first look", r"hands-on", r"unboxing",
    r"buy now", r"available now", r"price starting at",
    r"our pick", r"best .* of \d{4}",
    # 纯评论/互动邀请
    r"opinion:", r"editorial:", r"letter to the editor",
    r"commentary:", r"analysis:", r"what do you think",
    r"poll:", r"vote now", r"survey",
    # 编辑/预告
    r"coming soon", r"preview:", r"what to watch",
    r"what to read", r"what to know", r"things to know",
    r"what happened", r"weekly recap", r"daily briefing",
    r"today's essential", r"must-read",
    # 指南/解释型内容（不要求 ^ 开头，用 word boundary 匹配）
    r"\bwhat to know about\b",
    r"\ba guide to\b",
    r"\bexplainer[:\s]",
    r"\bq&a[:\s]",
    r"\bask [a-z]+:",
]


def is_non_news(item) -> bool:
    """判断是否为非新闻内容（征集、推广、播客、指南等）

    支持 NewsItem 对象和 dict 两种输入。

    匹配方式：不依赖标题绝对开头，使用 word boundary 匹配，
    即使标题有前缀、编号、标点也能识别。
    """
    if hasattr(item, "title"):
        title = item.title
        summary = item.summary
    else:
        title = item.get("title", "")
        summary = item.get("summary", "")

    text = (title + " " + summary).lower()

    for pattern in NON_NEWS_PATTERNS:
        if re.search(pattern, text):
            return True
    return False
