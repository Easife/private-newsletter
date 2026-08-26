"""
新闻去重与事件聚类

负责识别重复报道和同一事件的多源报道，合并为新闻分组。

三档分组策略：
  1. 高度相似（≥ high_threshold）：同一事件，合并为"精确匹配组"
  2. 中间区域（low_threshold ≤ sim < high_threshold）：相关报道，组成"相关报道组"
  3. 明显不相似（< low_threshold）：独立新闻，保持为"单条组"

每个组保留所有原始新闻的完整信息（URL、summary、source）。
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .fetcher import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class NewsGroup:
    """新闻组 - 包含一条或多条相关新闻

    Attributes:
        group_id: 组唯一标识（格式：group_{leader_index}）
        items: 组内所有新闻条目
        group_type: 组类型
            - "exact_match": 高度相似，同一事件的多源报道
            - "related": 中间区域，相关但不完全相同
            - "single": 独立新闻，无相似条目
        leader_index: 主条目在原始列表中的索引（用于排序）
        similarity_scores: 组内条目两两之间的相似度（可选）
    """
    group_id: str
    items: list[NewsItem]
    group_type: str  # "exact_match" | "related" | "single"
    leader_index: int  # 原始列表中的索引
    similarity_scores: list[tuple[int, int, float]] = field(default_factory=list)

    @property
    def leader(self) -> NewsItem:
        """主条目（第一个条目）"""
        return self.items[0]

    @property
    def source_count(self) -> int:
        """来源数量"""
        return len(self.items)

    @property
    def all_sources(self) -> list[dict]:
        """所有来源（去重后）"""
        seen = set()
        sources = []
        for item in self.items:
            for src in item.sources:
                if src["name"] not in seen:
                    seen.add(src["name"])
                    sources.append(src)
        return sources

    @property
    def all_urls(self) -> list[str]:
        """所有 URL"""
        return [item.primary_url for item in self.items if item.primary_url]


def _extract_entities(title: str) -> set[str]:
    """从标题中提取关键实体，并做同义词归一化"""
    SYNONYM_MAP = {
        "jail": "prison", "jailed": "prison",
        "pm": "prime_minister", "ex-pm": "former_pm",
        "ex": "former",
        "back": "return", "returned": "return", "returning": "return",
        "moved": "transfer", "briefly": "brief",
        "killed": "death", "dead": "death", "dies": "death", "slain": "death", "fatal": "death",
        "strike": "attack", "strikes": "attack", "bombing": "attack",
        "blaze": "fire", "fires": "fire", "wildfire": "fire",
        "quake": "earthquake",
        "deport": "deportation", "deportees": "deportation", "deported": "deportation",
        "landslide": "collapse", "collapsed": "collapse", "caved": "collapse",
        "jailed": "prison",
    }
    entities = set()
    words = title.split()
    for w in words:
        clean = w.strip(".,;:!?\"'()-").lower()
        if clean and len(clean) > 1:
            normalized = SYNONYM_MAP.get(clean, clean)
            entities.add(normalized)
    return entities


def _entity_similarity(set_a: set, set_b: set) -> float:
    """计算实体集合的相似度（使用 Jaccard）"""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _tokenize(text: str) -> set[str]:
    """将文本分词为关键词集合

    简单实现：转小写，按非字母数字字符分割，过滤短词。
    对中文做字符级分割（MVP 简化处理）。
    """
    text = text.lower()
    # 英文按空格和标点分割
    english_words = set(re.findall(r"[a-z]{2,}", text))
    # 中文按字符分割（连续 2-4 字作为 n-gram）
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_ngrams = set()
    for n in [2, 3, 4]:
        for i in range(len(chinese_chars) - n + 1):
            chinese_ngrams.add("".join(chinese_chars[i : i + n]))
    return english_words | chinese_ngrams


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """计算 Jaccard 相似度"""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def group_news(
    items: list[NewsItem],
    high_threshold: float = 0.8,
    low_threshold: float = 0.5,
) -> list[NewsGroup]:
    """将新闻列表进行三档分组

    三档策略：
    - 高度相似（≥ high_threshold）：同一事件，合并为精确匹配组
    - 中间区域（low_threshold ≤ sim < high_threshold）：相关报道组
    - 明显不相似（< low_threshold）：独立新闻，单条组

    Args:
        items: 原始新闻列表
        high_threshold: 高度相似阈值（默认 0.8）
        low_threshold: 相似阈值下限（默认 0.5）

    Returns:
        新闻组列表
    """
    if not items:
        return []

    # 为每个条目预计算标题关键词和实体
    tokenized = [(item, _tokenize(item.title)) for item in items]
    entities = [(item, _extract_entities(item.title)) for item in items]

    # 计算所有两两之间的相似度（结合 Jaccard + 实体匹配）
    n = len(items)
    similarity_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            token_sim = _jaccard_similarity(tokenized[i][1], tokenized[j][1])
            ent_sim = _entity_similarity(entities[i][1], entities[j][1])
            # 混合策略：实体匹配可以弥补词汇差异
            # 如果实体高度重叠（≥0.5），降低词汇权重
            if ent_sim >= 0.5:
                sim = max(token_sim, 0.4 * token_sim + 0.6 * ent_sim)
            else:
                sim = max(token_sim, ent_sim * 0.85)
            similarity_matrix[i][j] = sim
            similarity_matrix[j][i] = sim

    # 用 Union-Find 聚类高度相似的条目
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # 合并高度相似的条目
    for i in range(n):
        for j in range(i + 1, n):
            if similarity_matrix[i][j] >= high_threshold:
                union(i, j)

    # 按聚类分组
    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    # 为每个聚类构建 NewsGroup
    groups = []
    for leader_idx, member_indices in clusters.items():
        if len(member_indices) == 1:
            # 单条新闻 - 检查是否与其他组有相关性
            idx = member_indices[0]
            group = NewsGroup(
                group_id=f"group_{idx}",
                items=[items[idx]],
                group_type="single",
                leader_index=idx,
            )
            groups.append(group)
        else:
            # 多条高度相似的新闻
            group_items = [items[idx] for idx in member_indices]

            # 收集组内的相似度分数
            sim_scores = []
            for i in range(len(member_indices)):
                for j in range(i + 1, len(member_indices)):
                    idx_i, idx_j = member_indices[i], member_indices[j]
                    sim_scores.append((idx_i, idx_j, similarity_matrix[idx_i][idx_j]))

            group = NewsGroup(
                group_id=f"group_{leader_idx}",
                items=group_items,
                group_type="exact_match",
                leader_index=min(member_indices),
                similarity_scores=sim_scores,
            )
            groups.append(group)

    # 检查单条新闻之间是否有相关性（中间区域）
    single_groups = [g for g in groups if g.group_type == "single"]
    related_pairs = []

    for i, g1 in enumerate(single_groups):
        for j, g2 in enumerate(single_groups):
            if i >= j:
                continue
            idx1 = g1.leader_index
            idx2 = g2.leader_index
            sim = similarity_matrix[idx1][idx2]
            if sim >= low_threshold:
                related_pairs.append((idx1, idx2, sim))

    # 将相关的单条新闻合并为相关报道组
    if related_pairs:
        # 用 Union-Find 合并相关的单条新闻
        single_parent = {g.leader_index: g.leader_index for g in single_groups}

        def single_find(x):
            while single_parent[x] != x:
                single_parent[x] = single_parent[single_parent[x]]
                x = single_parent[x]
            return x

        def single_union(x, y):
            rx, ry = single_find(x), single_find(y)
            if rx != ry:
                single_parent[rx] = ry

        for idx1, idx2, sim in related_pairs:
            single_union(idx1, idx2)

        # 按聚类分组
        single_clusters = defaultdict(list)
        for g in single_groups:
            leader_idx = g.leader_index
            single_clusters[single_find(leader_idx)].append(leader_idx)

        # 构建相关报道组
        new_groups = []
        for root, member_indices in single_clusters.items():
            if len(member_indices) == 1:
                # 仍然是单条
                idx = member_indices[0]
                new_groups.append(NewsGroup(
                    group_id=f"group_{idx}",
                    items=[items[idx]],
                    group_type="single",
                    leader_index=idx,
                ))
            else:
                # 相关报道组
                group_items = [items[idx] for idx in member_indices]
                sim_scores = []
                for i in range(len(member_indices)):
                    for j in range(i + 1, len(member_indices)):
                        idx_i, idx_j = member_indices[i], member_indices[j]
                        sim_scores.append((idx_i, idx_j, similarity_matrix[idx_i][idx_j]))

                new_groups.append(NewsGroup(
                    group_id=f"group_{min(member_indices)}",
                    items=group_items,
                    group_type="related",
                    leader_index=min(member_indices),
                    similarity_scores=sim_scores,
                ))

        # 替换单条组
        groups = [g for g in groups if g.group_type != "single"]
        groups.extend(new_groups)

    # 按 leader_index 排序
    groups.sort(key=lambda g: g.leader_index)

    # 统计
    exact_count = sum(1 for g in groups if g.group_type == "exact_match")
    related_count = sum(1 for g in groups if g.group_type == "related")
    single_count = sum(1 for g in groups if g.group_type == "single")
    total_items = sum(len(g.items) for g in groups)

    logger.info(
        f"分组：{len(items)} 条新闻 → {len(groups)} 组 "
        f"(精确匹配 {exact_count}, 相关报道 {related_count}, 独立 {single_count}) "
        f"总条目数: {total_items}"
    )

    return groups


def deduplicate(items: list[NewsItem], threshold: float = 0.6, low_threshold: float = 0.35) -> tuple[list[NewsItem], list[NewsGroup], dict]:
    """对新闻列表进行去重，返回 3 值以兼容主流程

    Args:
        items: 原始新闻列表
        threshold: 标题相似度阈值，超过此值视为同一事件（作为 high_threshold）
        low_threshold: 相关报道阈值下限，低于此值视为独立新闻

    Returns:
        (deduped_items, news_groups, dedup_stats)
        - deduped_items: 去重后的新闻列表（每个组的 leader，sources 已合并）
        - news_groups: 新闻分组列表
        - dedup_stats: 统计信息字典
    """
    groups = group_news(items, high_threshold=threshold, low_threshold=low_threshold)

    # 展平：每个组保留 leader，合并组内所有来源
    deduped = []
    for g in groups:
        leader = g.leader
        merged_sources = g.all_sources
        if merged_sources and merged_sources != leader.sources:
            # 创建新对象，保留 leader 的其他属性，更新 sources
            leader = NewsItem(
                title=leader.title,
                summary=leader.summary,
                language=leader.language,
                tags=leader.tags,
                published=leader.published,
                sources=merged_sources,
            )
        deduped.append(leader)

    # 统计
    exact_count = sum(1 for g in groups if g.group_type == "exact_match")
    related_count = sum(1 for g in groups if g.group_type == "related")
    single_count = sum(1 for g in groups if g.group_type == "single")

    stats = {
        "input_count": len(items),
        "output_count": len(groups),
        "exact_match": exact_count,
        "related": related_count,
        "single": single_count,
    }

    logger.info(
        f"去重：{len(items)} 条 → {len(groups)} 组 "
        f"(精确匹配 {exact_count}, 相关报道 {related_count}, 独立 {single_count})"
    )

    return deduped, groups, stats
