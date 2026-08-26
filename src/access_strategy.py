"""
来源访问策略

基于 source_strategy.yaml，为每个新闻组选择最佳来源组合。

策略规则：
1. 选择 authority_priority 最高的来源作为 Primary
2. 如果 Primary 是 free → 只保留 Primary
3. 如果 Primary 是 paid → 寻找 free Alternative
4. 如果有 free Alternative → 保留 Primary + Alternative
5. 如果没有 free Alternative → 保留 Primary + Google 搜索链接
6. 始终保留原始 URL
"""

import logging
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .dedup import NewsGroup

logger = logging.getLogger(__name__)


@dataclass
class SourceInfo:
    """来源信息"""
    name: str
    display_name: str
    authority_priority: int  # 1=最高
    access_type: str  # "free" | "paid" | "unknown"
    language: str


@dataclass
class AccessStrategy:
    """单个新闻组的访问策略结果

    Attributes:
        group_id: 新闻组 ID
        primary: 主来源信息
        primary_url: 主来源 URL
        primary_item_index: 主来源在 NewsGroup.items 中的索引
        alternative: 备选免费来源（可选）
        alternative_url: 备选来源 URL
        alternative_item_index: 备选来源在 NewsGroup.items 中的索引
        google_search_url: Google 搜索链接（无免费替代时生成）
        strategy_type: 策略类型
            - "free_primary": 主来源免费
            - "paid_with_free_alt": 主来源付费，有免费替代
            - "paid_no_alt": 主来源付费，无免费替代
    """
    group_id: str
    primary: Optional[SourceInfo] = None
    primary_url: str = ""
    primary_item_index: int = 0
    alternative: Optional[SourceInfo] = None
    alternative_url: str = ""
    alternative_item_index: int = -1
    google_search_url: str = ""
    strategy_type: str = "unknown"


class AccessStrategyEngine:
    """来源访问策略引擎"""

    def __init__(self, config_path: str = None):
        """初始化引擎

        Args:
            config_path: source_strategy.yaml 路径
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "source_strategy.yaml",
            )

        self.sources = self._load_config(config_path)
        self._source_map = {s["name"]: s for s in self.sources}

    def _load_config(self, config_path: str) -> list[dict]:
        """加载来源策略配置"""
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("sources", [])

    def get_source_info(self, source_name: str) -> Optional[SourceInfo]:
        """获取来源信息"""
        src = self._source_map.get(source_name)
        if not src:
            return None

        return SourceInfo(
            name=src["name"],
            display_name=src.get("display_name", src["name"]),
            authority_priority=src.get("authority_priority", 99),
            access_type=src.get("access_type", "unknown"),
            language=src.get("language", "en"),
        )

    def _generate_google_search_url(self, title: str) -> str:
        """生成 Google 搜索链接"""
        encoded_title = urllib.parse.quote(title)
        return f"https://www.google.com/search?q={encoded_title}"

    def apply_strategy(self, group: NewsGroup) -> AccessStrategy:
        """对单个新闻组应用访问策略

        Args:
            group: 新闻组

        Returns:
            访问策略结果
        """
        strategy = AccessStrategy(group_id=group.group_id)

        # 收集组内所有来源信息
        source_candidates = []
        for idx, item in enumerate(group.items):
            for src in item.sources:
                info = self.get_source_info(src["name"])
                if info:
                    source_candidates.append({
                        "info": info,
                        "url": src.get("url", ""),
                        "item_index": idx,
                        "weight": src.get("weight", 0.5),
                    })

        if not source_candidates:
            # 没有匹配的来源信息，使用第一个条目
            if group.items:
                item = group.items[0]
                src = item.sources[0] if item.sources else {}
                strategy.primary = SourceInfo(
                    name=src.get("name", "unknown"),
                    display_name=src.get("name", "unknown"),
                    authority_priority=99,
                    access_type="unknown",
                    language="en",
                )
                strategy.primary_url = src.get("url", "")
                strategy.primary_item_index = 0
                strategy.strategy_type = "free_primary"
            return strategy

        # 按 authority_priority 排序（数字越小优先级越高）
        source_candidates.sort(key=lambda x: (x["info"].authority_priority, x["weight"]))

        # 选择 Primary（authority_priority 最高）
        primary = source_candidates[0]
        strategy.primary = primary["info"]
        strategy.primary_url = primary["url"]
        strategy.primary_item_index = primary["item_index"]

        # 判断 Primary 是否免费
        if primary["info"].access_type == "free":
            strategy.strategy_type = "free_primary"
            return strategy

        # Primary 是付费，寻找免费 Alternative
        free_alternatives = [
            c for c in source_candidates[1:]
            if c["info"].access_type == "free"
        ]

        if free_alternatives:
            # 选择 authority_priority 最高的免费来源
            alt = free_alternatives[0]
            strategy.alternative = alt["info"]
            strategy.alternative_url = alt["url"]
            strategy.alternative_item_index = alt["item_index"]
            strategy.strategy_type = "paid_with_free_alt"
        else:
            # 没有免费替代，生成 Google 搜索链接
            strategy.google_search_url = self._generate_google_search_url(group.leader.title)
            strategy.strategy_type = "paid_no_alt"

        return strategy

    def apply_to_groups(self, groups: list[NewsGroup]) -> list[AccessStrategy]:
        """对所有新闻组应用访问策略

        Args:
            groups: 新闻组列表

        Returns:
            访问策略结果列表
        """
        results = []
        for group in groups:
            strategy = self.apply_strategy(group)
            results.append(strategy)

        # 统计
        free_count = sum(1 for s in results if s.strategy_type == "free_primary")
        paid_with_alt = sum(1 for s in results if s.strategy_type == "paid_with_free_alt")
        paid_no_alt = sum(1 for s in results if s.strategy_type == "paid_no_alt")

        logger.info(
            f"访问策略: {len(results)} 组 "
            f"(免费主源 {free_count}, 付费+免费替代 {paid_with_alt}, "
            f"付费无替代 {paid_no_alt})"
        )

        return results
