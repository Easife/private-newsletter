"""
新闻获取层

负责从配置的新闻源抓取新闻。第一阶段通过 RSS 获取，
但架构上设计为"新闻发现与获取层"，未来可扩展搜索引擎、
新闻 API 等其他获取方式。

数据流：
  sources.yaml → fetch_rss() → [NewsItem, ...]
"""

import json
import logging
import os
import signal
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """标准化的新闻条目

    sources 字段保存所有来源信息（名称、URL、权重）。
    去重合并时，多个来源会被追加到 sources 列表中，
    确保最终简报能列出所有真实的来源链接。
    """

    title: str
    summary: str
    language: str
    tags: list[str] = field(default_factory=list)
    published: Optional[str] = None  # RSS 原始时间字符串
    sources: list[dict] = field(default_factory=list)
    # 每个 source dict: {"name": str, "url": str, "weight": float}
    image_url: Optional[str] = None  # RSS 提供的新闻图片 URL

    @property
    def primary_source_name(self) -> str:
        """主来源名称（第一个来源）"""
        return self.sources[0]["name"] if self.sources else ""

    @property
    def primary_url(self) -> str:
        """主来源 URL（第一个来源）"""
        return self.sources[0].get("url", "") if self.sources else ""

    @property
    def source_names(self) -> str:
        """所有来源名称，逗号分隔"""
        return ", ".join(s["name"] for s in self.sources)


def fetch_from_source(source: dict, timeout: int = 15, ssl_verify: bool = False, proxies: dict | None = None) -> list[NewsItem]:
    """从单个新闻源获取新闻

    使用 requests 发送带超时的 HTTP 请求获取 RSS 内容，
    再交给 feedparser 解析。这确保单个源不会无限期阻塞。

    对格式异常的 entry 进行容错处理，跳过无法解析的条目。

    Args:
        source: 单个来源配置字典
        timeout: HTTP 请求超时秒数
        ssl_verify: 是否验证 SSL 证书（代理环境下建议 False）
        proxies: 代理配置字典，如 {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    """
    source_name = source.get("name", "unknown")
    items = []

    try:
        # 先用 requests 获取 RSS 内容（带超时和代理）
        resp = requests.get(
            source["rss_url"],
            timeout=timeout,
            headers={"User-Agent": "PrivateNewsletter/1.0"},
            verify=ssl_verify,
            proxies=proxies,
        )
        resp.raise_for_status()

        # 再用 feedparser 解析已获取的内容
        feed = feedparser.parse(resp.content)

        if feed.bozo and not feed.entries:
            logger.warning(f"RSS 解析警告 [{source_name}]: {feed.bozo_exception}")
            return []

        for entry in feed.entries:
            try:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                # 摘要处理：优先使用 summary，其次 description
                summary = entry.get("summary", entry.get("description", "")).strip()
                # 去除 HTML 标签
                if "<" in summary:
                    summary = BeautifulSoup(summary, "html.parser").get_text()

                url = entry.get("link", "")
                published = entry.get("published", entry.get("updated", None))

                # 提取图片：优先 media_content 中最大的图片
                image_url = None
                media_content = entry.get("media_content", [])
                if media_content:
                    # 按宽度排序，取最大的
                    valid_media = [m for m in media_content if m.get("medium") == "image" and m.get("url")]
                    if valid_media:
                        valid_media.sort(key=lambda m: int(m.get("width", 0)), reverse=True)
                        image_url = valid_media[0]["url"]

                items.append(
                    NewsItem(
                        title=title,
                        summary=summary[:500],
                        language=source.get("language", "en"),
                        tags=source.get("tags", []),
                        published=published,
                        sources=[{
                            "name": source_name,
                            "url": url,
                            "weight": source.get("weight", 0.5),
                        }],
                        image_url=image_url,
                    )
                )
            except Exception as e:
                logger.debug(f"跳过异常条目 [{source_name}]: {e}")
                continue

        logger.info(f"[{source_name}] 获取 {len(items)} 条新闻")

    except requests.exceptions.Timeout:
        logger.warning(f"[{source_name}] 请求超时 ({timeout}s)")
    except requests.exceptions.SSLError as e:
        logger.warning(f"[{source_name}] SSL 错误: {e}")
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"[{source_name}] 连接失败: {e}")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.warning(f"[{source_name}] HTTP 错误 {status}: {e}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[{source_name}] 请求异常: {e}")
    except Exception as e:
        logger.warning(f"[{source_name}] 未知错误: {e}")

    return items


def fetch_all(sources: list[dict], timeout: int = 15, max_concurrent: int = 5, ssl_verify: bool = False, proxies: dict | None = None) -> list[NewsItem]:
    """从所有配置的新闻源并发获取新闻

    Args:
        sources: sources.yaml 中的 sources 列表
        timeout: 每个请求的超时秒数
        max_concurrent: 最大并发数
        ssl_verify: 是否验证 SSL 证书（代理环境下建议 False）
        proxies: 代理配置字典

    Returns:
        所有来源的新闻列表（未去重）
    """
    all_items = []
    success_sources = []
    failed_sources = []

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_source = {
            executor.submit(fetch_from_source, source, timeout, ssl_verify, proxies): source
            for source in sources
        }
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            source_name = source.get("name", "unknown")
            try:
                items = future.result()
                all_items.extend(items)
                if items:
                    success_sources.append(f"{source_name}({len(items)}条)")
                else:
                    failed_sources.append(f"{source_name}(0条)")
            except Exception as e:
                failed_sources.append(f"{source_name}({type(e).__name__})")
                logger.error(f"[{source_name}] 获取异常: {e}")

    # 输出来源状态汇总
    logger.info(f"来源状态: 成功 {len(success_sources)}/{len(sources)}, 失败 {len(failed_sources)}/{len(sources)}")
    if success_sources:
        logger.info(f"  成功: {', '.join(success_sources)}")
    if failed_sources:
        logger.info(f"  失败: {', '.join(failed_sources)}")
    logger.info(f"总计获取 {len(all_items)} 条新闻（来自 {len(sources)} 个源）")

    return all_items


# ============================================================
# 序列化：支持跨阶段传递（Windows fetch → WSL 处理）
# ============================================================

def save_raw_news(items: list[NewsItem], filepath: str) -> None:
    """将 NewsItem 列表保存为 JSON 文件

    用于 Windows 侧完成 fetch 后，将原始新闻数据持久化，
    供 WSL 侧后续处理。
    """
    data = []
    for item in items:
        record = {
            "title": item.title,
            "summary": item.summary,
            "language": item.language,
            "tags": item.tags,
            "published": item.published,
            "sources": item.sources,
        }
        if item.image_url:
            record["image_url"] = item.image_url
        data.append(record)

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"原始新闻已保存到 {filepath} ({len(items)} 条)")


def load_raw_news(filepath: str) -> list[NewsItem]:
    """从 JSON 文件恢复 NewsItem 列表

    与 save_raw_news 配对使用，确保数据完整还原。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    for record in data:
        items.append(NewsItem(
            title=record["title"],
            summary=record["summary"],
            language=record["language"],
            tags=record.get("tags", []),
            published=record.get("published"),
            sources=record.get("sources", []),
            image_url=record.get("image_url"),
        ))

    logger.info(f"从 {filepath} 加载 {len(items)} 条原始新闻")
    return items
