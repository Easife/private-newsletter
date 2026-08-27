"""每日运行缓存

本项目是每日简报，not 新闻流，因此不做跨日期增量评分。
每天作为一次独立 run，缓存按日期隔离保存在 cache/YYYY-MM-DD/ 下：

    raw_news.json        原始抓取新闻列表
    dedup_groups.json    去重分组结果（groups + 每条新闻）
    ranking.json         LLM 候选池评分结果
    translation.json     翻译结果

运行模式：
- resume：当天缓存完整时，完整复用 raw/dedup/ranking/translation 缓存，
  只重新生成 selected_news 和 HTML。翻译成功率仅作质量指标展示，
  不改变 resume 的复用语义（不会因成功率低而自动重翻）。
- refresh：删除当天 cache 目录，从 RSS 抓取开始完整重跑。
- retranslate-only（预留独立操作）：复用 raw/dedup/ranking，仅重新翻译。

不实现跨日期新闻评分复用。
"""

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from .fetcher import NewsItem, save_raw_news, load_raw_news
from .dedup import NewsGroup

CACHE_FILES = ("raw_news.json", "dedup_groups.json", "ranking.json", "translation.json")
TRANSLATION_STATS_FILE = "translation_stats.json"


def translation_success_rate(all_translated: list[dict]) -> float:
    """统计翻译成功率 = 成功翻译数量 / 总数量

    成功定义：该条目的 err_title 和 err_summary 均为空（Google/Bing/LLM 任一层成功）。
    返回 0.0 ~ 1.0 的小数；空列表返回 1.0（无失败即视为高质量）。
    """
    if not all_translated:
        return 1.0
    total = len(all_translated)
    success = sum(
        1 for t in all_translated
        if not t.get("err_title") and not t.get("err_summary")
    )
    return round(success / total, 4)


def _item_to_dict(item: NewsItem) -> dict:
    """NewsItem → dict（保存原始抓取的 NewsItem，用于 raw 缓存）"""
    record = {
        "title": item.title,
        "summary": item.summary,
        "language": item.language,
        "tags": list(item.tags),
        "published": item.published,
        "sources": item.sources,
    }
    if item.image_url:
        record["image_url"] = item.image_url
    return record


def _dict_to_item(record: dict) -> NewsItem:
    """dict → NewsItem（与 _item_to_dict 配对）"""
    return NewsItem(
        title=record["title"],
        summary=record["summary"],
        language=record["language"],
        tags=record.get("tags", []),
        published=record.get("published"),
        sources=record.get("sources", []),
        image_url=record.get("image_url"),
    )


def _group_to_dict(group: NewsGroup) -> dict:
    """NewsGroup → dict"""
    return {
        "group_id": group.group_id,
        "items": [_item_to_dict(it) for it in group.items],
        "group_type": group.group_type,
        "leader_index": group.leader_index,
        "similarity_scores": [list(t) for t in group.similarity_scores],
    }


def _dict_to_group(record: dict) -> NewsGroup:
    """dict → NewsGroup（与 _group_to_dict 配对）"""
    return NewsGroup(
        group_id=record["group_id"],
        items=[_dict_to_item(it) for it in record["items"]],
        group_type=record["group_type"],
        leader_index=record["leader_index"],
        similarity_scores=[tuple(t) for t in record.get("similarity_scores", [])],
    )


def cache_root(project_root: str = "") -> str:
    """cache 根目录"""
    if project_root:
        return os.path.join(project_root, "cache")
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")


def cache_dir(project_root: str, date: str) -> str:
    """当天缓存目录 cache/YYYY-MM-DD/"""
    return os.path.join(cache_root(project_root), date)


def is_complete(cache_root_dir: str) -> bool:
    """当天缓存是否完整（4 个文件都在）"""
    return all(os.path.isfile(os.path.join(cache_root_dir, f)) for f in CACHE_FILES)


def delete(dir_path: str) -> None:
    """删除缓存目录"""
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path)


def ensure_dir(dir_path: str) -> None:
    os.makedirs(dir_path, exist_ok=True)


# ============================================================
# 各阶段读写
# ============================================================

def save_raw(items: list[NewsItem], dir_path: str) -> None:
    ensure_dir(dir_path)
    save_raw_news(items, os.path.join(dir_path, "raw_news.json"))


def load_raw(dir_path: str) -> list[NewsItem]:
    return load_raw_news(os.path.join(dir_path, "raw_news.json"))


def save_dedup_groups(
    news_groups: list[NewsGroup],
    deduped_items: list[NewsItem],
    dedup_stats: dict,
    dir_path: str,
) -> None:
    ensure_dir(dir_path)
    data = {
        "news_groups": [_group_to_dict(g) for g in news_groups],
        "deduped_items": [_item_to_dict(it) for it in deduped_items],
        "dedup_stats": dedup_stats,
    }
    with open(os.path.join(dir_path, "dedup_groups.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_dedup_groups(dir_path: str) -> tuple[list[NewsGroup], list[NewsItem], dict]:
    with open(os.path.join(dir_path, "dedup_groups.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    news_groups = [_dict_to_group(g) for g in data["news_groups"]]
    deduped_items = [_dict_to_item(it) for it in data["deduped_items"]]
    return news_groups, deduped_items, data["dedup_stats"]


def save_ranking(candidates_result: list[dict], dir_path: str) -> None:
    ensure_dir(dir_path)
    with open(os.path.join(dir_path, "ranking.json"), "w", encoding="utf-8") as f:
        json.dump(candidates_result, f, ensure_ascii=False, indent=2)


def load_ranking(dir_path: str) -> list[dict]:
    with open(os.path.join(dir_path, "ranking.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def save_translation(all_translated: list[dict], dir_path: str) -> None:
    ensure_dir(dir_path)
    with open(os.path.join(dir_path, "translation.json"), "w", encoding="utf-8") as f:
        json.dump(all_translated, f, ensure_ascii=False, indent=2)
    _save_translation_stats(all_translated, dir_path)


def load_translation(dir_path: str) -> list[dict]:
    with open(os.path.join(dir_path, "translation.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _save_translation_stats(all_translated: list[dict], dir_path: str) -> None:
    """保存翻译质量统计（独立文件，不改变 translation.json 的 list 结构）"""
    stats = {
        "total": len(all_translated),
        "success_rate": translation_success_rate(all_translated),
    }
    try:
        with open(os.path.join(dir_path, TRANSLATION_STATS_FILE), "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_translation_stats(dir_path: str) -> dict:
    """读取翻译质量统计；无 stats 文件时利用 translation.json 计算"""
    stats_path = os.path.join(dir_path, TRANSLATION_STATS_FILE)
    if os.path.isfile(stats_path):
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
            return {
                "total": stats.get("total", 0),
                "success_rate": stats.get("success_rate", 1.0),
            }
        except Exception:
            pass
    all_translated = load_translation(dir_path)
    return {
        "total": len(all_translated),
        "success_rate": translation_success_rate(all_translated),
    }