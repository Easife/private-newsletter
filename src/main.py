"""
管道主流程

串联获取 → 日期筛选 → 去重 → 非新闻过滤 → LLM 选择 → 翻译 → 格式化的完整流程。

设计原则：
- LLM 只负责选择和排序（select_headlines），不重新撰写新闻
- RSS 原始 summary 就是新闻摘要，翻译后直接使用
- 非新闻过滤使用公共模块 src/non_news_filter.py
"""

import json as json_module
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .dedup import deduplicate
from .fetcher import NewsItem, fetch_all, save_raw_news, load_raw_news
from .formatter import format_newsletter
from .llm import select_headlines
from .non_news_filter import is_non_news

logger = logging.getLogger(__name__)


def _load_yaml(filepath: str) -> dict:
    """加载 YAML 配置文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_date_from_published(published: Optional[str]) -> Optional[str]:
    """尝试从 RSS 的 published 字段解析出日期字符串 (YYYY-MM-DD)

    支持常见 RSS 时间格式：
    - RFC 2822: "Mon, 18 Aug 2026 10:00:00 +0800"
    - ISO 8601: "2026-08-18T10:00:00Z"
    - 简单日期: "2026-08-18"

    解析失败返回 None，调用方应保留该条目（不过滤）。
    """
    if not published:
        return None

    s = published.strip()

    # 尝试 ISO 8601 格式
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 尝试 RFC 2822 格式（RSS 标准）
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    # 尝试提取开头的日期部分 "2026-08-18..."
    import re
    match = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if match:
        return match.group(1)

    return None


def _filter_by_date(items: list[NewsItem], target_date: str) -> list[NewsItem]:
    """按日期筛选新闻条目

    MVP 策略：
    - 能解析出日期的条目：只保留日期匹配的
    - 无法解析日期的条目：保留（宁多勿漏，因为部分 RSS 时间字段不可靠）
    - 保留一个小时前的容差窗口，处理时区差异

    Args:
        items: 原始新闻列表
        target_date: 目标日期 (YYYY-MM-DD)

    Returns:
        筛选后的新闻列表
    """
    filtered = []
    skipped_no_date = 0
    skipped_wrong_date = 0

    for item in items:
        parsed_date = _parse_date_from_published(item.published)
        if parsed_date is None:
            # 无法解析日期，保留该条目
            skipped_no_date += 1
            filtered.append(item)
        elif parsed_date == target_date:
            filtered.append(item)
        else:
            skipped_wrong_date += 1

    logger.info(
        f"日期筛选 ({target_date}): "
        f"{len(items)} → {len(filtered)} 条 "
        f"(跳过 {skipped_wrong_date} 条非目标日期, "
        f"保留 {skipped_no_date} 条无日期信息)"
    )
    return filtered


# ============================================================
# Windows Python 翻译代理调用
# ============================================================

# 项目根目录（自动检测）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Windows 端 Python 解释器路径（WSL 视角，自动检测）
WIN_PYTHON = str(Path(sys.executable)) if sys.platform == "win32" else None
if sys.platform != "win32" and WIN_PYTHON is None:
    # WSL 环境：尝试常见 Windows Python 路径
    for candidate in [
        "/mnt/c/Users/qing4/AppData/Local/Programs/Python/Python311/python.exe",
        "/mnt/c/Program Files/Python311/python.exe",
        "/mnt/c/Program Files (x86)/Python311/python.exe",
    ]:
        if os.path.exists(candidate):
            WIN_PYTHON = candidate
            break

# Windows 端项目根路径（Windows 视角，用于传递给 Windows Python）
# 将 WSL 路径转换为 Windows 路径，或从 Windows 环境直接获取
if sys.platform == "win32":
    WIN_PROJECT_WIN = str(PROJECT_ROOT)
else:
    # WSL: /mnt/d/... → D:\...
    win_path = str(PROJECT_ROOT)
    if win_path.startswith("/mnt/"):
        drive = win_path[5].upper()
        rest = win_path[6:].replace("/", "\\")
        WIN_PROJECT_WIN = f"{drive}:{rest}"
    else:
        WIN_PROJECT_WIN = win_path

WIN_TRANSLATE_SCRIPT_WIN = f"{WIN_PROJECT_WIN}\\translate_news_windows.py"


def _call_windows_translate(items: list[NewsItem], timeout: int = 600) -> list:
    """通过 Windows Python 调用 Google Translate

    流程：
    1. 序列化 items 到 JSON（item_index = combined list 中的1-based 索引）
    2. 写入 Windows 端 input 文件（使用 Windows 路径）
    3. 调用 Windows Python 运行 translate_news_windows.py
    4. 读取 Windows 端 output 文件
    """
    # 1. 序列化
    items_json = []
    for i, item in enumerate(items, 1):
        items_json.append({
            "item_index": i,
            "title": item.title,
            "summary": item.summary,
            "language": item.language,
        })

    # 2. 准备临时文件路径（使用 Windows 路径格式）
    input_dir_win = f"{WIN_PROJECT_WIN}\\data\\translation"
    input_path_win = f"{input_dir_win}\\translate_input.json"
    output_path_win = f"{input_dir_win}\\translate_output.json"

    # WSL 视角路径（基于项目根目录）
    translation_dir = PROJECT_ROOT / "data" / "translation"
    input_path_wsl = str(translation_dir / "translate_input.json")
    output_path_wsl = str(translation_dir / "translate_output.json")

    # 创建目录并写入文件
    translation_dir.mkdir(parents=True, exist_ok=True)
    with open(input_path_wsl, "w", encoding="utf-8") as f:
        json_module.dump(items_json, f, ensure_ascii=False, indent=2)

    # 3. 调用 Windows Python（使用 Windows 路径）
    cmd = [
        WIN_PYTHON, WIN_TRANSLATE_SCRIPT_WIN,
        "--input", input_path_win,
        "--output", output_path_win,
    ]
    logger.info(f"调用 Windows Python: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(f"Windows 翻译失败 (code {result.returncode}): {result.stderr[:500]}")
            return []
        # 输出 Windows 端的 print 日志
        for line in result.stdout.splitlines():
            if line.strip():
                logger.info(f"[Windows] {line}")

        # 4. 读取输出（用 WSL 路径）
        if not os.path.exists(output_path_wsl):
            logger.error(f"Windows 输出文件不存在: {output_path_wsl}")
            return []
        with open(output_path_wsl, "r", encoding="utf-8") as f:
            return json_module.load(f)
    except subprocess.TimeoutExpired:
        logger.error(f"Windows 翻译超时 ({timeout}s)")
        return []
    except Exception as e:
        logger.error(f"Windows 翻译异常: {e}")
        return []


def run(
    config_dir: str = "config",
    output_dir: str = "output",
    date: Optional[str] = None,
    model: Optional[str] = None,
    raw_file: Optional[str] = None,
    load_raw: Optional[str] = None,
) -> Optional[str]:
    """运行完整的新闻简报生成流程

    流程：
    1. 加载配置
    2. 获取/加载 RSS
    3. 日期筛选
    4. 去重（合并多来源）
    5. 非新闻过滤
    6. select_headlines（LLM 选择 Top 10）
    7. 翻译（标题 + RSS 摘要）
    8. 输出 Markdown + JSON + HTML

    Args:
        config_dir: 配置文件目录
        output_dir: 输出目录
        date: 指定日期（YYYY-MM-DD），默认今天。用于筛选新闻和输出文件名。
        model: LLM 模型选择
        raw_file: 执行 fetch 后将原始新闻保存到此 JSON 文件（不执行后续处理）
        load_raw: 从 JSON 文件加载原始新闻，跳过 fetch 阶段

    Returns:
        生成的简报文件路径，失败返回 None
    """
    # 默认使用今天的日期
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info("=" * 50)
    logger.info(f"开始生成每日新闻简报 ({date})")
    logger.info("=" * 50)

    timings = []  # [(阶段名, 耗时秒数)]
    t_total = time.time()

    # ============================================================
    # 1. 加载配置
    # ============================================================
    logger.info("加载配置文件...")

    try:
        sources_config = _load_yaml(os.path.join(config_dir, "sources.yaml"))
        interests_config = _load_yaml(os.path.join(config_dir, "interests.yaml"))
        newsletter_config = _load_yaml(os.path.join(config_dir, "newsletter.yaml"))
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        return None

    sources = sources_config.get("sources", [])
    long_term = interests_config.get("long_term") or []
    recent = interests_config.get("recent") or []
    sections = newsletter_config.get("sections", [])
    fetch_config = newsletter_config.get("fetch", {})
    output_config = newsletter_config.get("output", {})

    # 代理配置：优先使用配置文件，其次使用环境变量
    proxy_url = fetch_config.get("proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    logger.info(f"新闻源: {len(sources)} 个")
    logger.info(f"长期兴趣: {len(long_term)} 项")
    logger.info(f"近期关注: {len(recent)} 项")
    if proxies:
        logger.info(f"代理: {proxy_url}")

    # ============================================================
    # 2. 获取新闻
    # ============================================================
    t_phase = time.time()
    if load_raw:
        # 从 JSON 文件加载原始新闻（跳过 fetch）
        logger.info(f"从 JSON 文件加载原始新闻: {load_raw}")
        all_items = load_raw_news(load_raw)
    else:
        # 正常 fetch 流程
        logger.info("正在获取新闻...")
        all_items = fetch_all(
            sources,
            timeout=fetch_config.get("timeout", 15),
            max_concurrent=fetch_config.get("max_concurrent", 5),
            ssl_verify=fetch_config.get("ssl_verify", False),
            proxies=proxies,
        )

    if not all_items:
        logger.error("未获取到任何新闻，请检查网络和新闻源配置")
        return None
    timings.append(("RSS 抓取", time.time() - t_phase))

    # ============================================================
    # 2.5 保存原始新闻（仅 fetch 模式 + 指定了 raw_file）
    # ============================================================
    if raw_file and not load_raw:
        save_raw_news(all_items, raw_file)
        logger.info(f"原始新闻已保存，后续处理未执行。可用以下命令继续处理：")
        logger.info(f"  python run.py --load-raw {raw_file}")
        return raw_file

    # ============================================================
    # 3. 按目标日期筛选
    # ============================================================
    t_phase = time.time()
    logger.info(f"按日期筛选 ({date})...")

    dated_items = _filter_by_date(all_items, date)

    if not dated_items:
        logger.warning(f"目标日期 {date} 没有匹配的新闻，尝试使用全部新闻")
        dated_items = all_items
    timings.append(("日期筛选", time.time() - t_phase))

    # ============================================================
    # 4. 去重
    # ============================================================
    t_phase = time.time()
    logger.info("正在去重...")

    threshold = fetch_config.get("dedup_threshold", 0.6)
    dedup_config = newsletter_config.get("dedup", {})
    low_threshold = dedup_config.get("low_threshold", 0.35)
    deduped_items, news_groups, dedup_stats = deduplicate(
        dated_items, threshold=threshold, low_threshold=low_threshold
    )
    timings.append(("去重", time.time() - t_phase))

    # 构建 item → group 映射（供后续步骤使用 group 信息）
    item_to_group = {}
    for g in news_groups:
        if g.group_type == "exact_match":
            for item in deduped_items:
                if item.title == g.leader.title:
                    item_to_group[id(item)] = g
                    break
        else:
            for item in g.items:
                item_to_group[id(item)] = g

    # ============================================================
    # 4.5 非新闻内容过滤
    # ============================================================
    t_phase = time.time()
    before_count = len(deduped_items)
    deduped_items = [item for item in deduped_items if not is_non_news(item)]
    removed = before_count - len(deduped_items)
    if removed > 0:
        logger.info(f"非新闻过滤: 移除 {removed} 条, 剩余 {len(deduped_items)} 条")
    timings.append(("非新闻过滤", time.time() - t_phase))

    # ============================================================
    # 5. LLM 选择头版（group 级别）
    # ============================================================
    t_phase = time.time()
    logger.info("第一轮 LLM: 头版筛选...")

    # 构建 group 代表列表：每个 group 只选一条代表送 LLM
    group_representatives = []  # [(representative_item, NewsGroup)]
    for g in news_groups:
        if g.group_type == "related":
            rep = max(g.items, key=lambda x: len(x.sources))
            group_representatives.append((rep, g))
        else:
            group_representatives.append((g.leader, g))

    rep_items = [rep for rep, g in group_representatives]
    headlines_result = select_headlines(items=rep_items, model=model)

    if not headlines_result:
        logger.error("头版筛选失败")
        return None

    logger.info(f"头版筛选完成: {len(headlines_result)} 条")
    timings.append(("头条筛选 (LLM)", time.time() - t_phase))

    # 展开选中的 group（group 级别，不平铺 related 成员）
    selected_groups = []
    selected_group_ids = set()
    for h in headlines_result:
        idx = h["item_index"]  # 1-based into group_representatives
        if idx < 1 or idx > len(group_representatives):
            logger.error(f"item_index {idx} 超出范围，跳过")
            continue
        rep, group = group_representatives[idx - 1]
        selected_group_ids.add(group.group_id)
        selected_groups.append(group)

    # 普通新闻候选 = dedup 后全部新闻 - 头版 group 内所有新闻
    selected_item_ids = set()
    for g in selected_groups:
        for item in g.items:
            selected_item_ids.add(id(item))
    ordinary_candidates = [
        item for item in deduped_items
        if id(item) not in selected_item_ids
    ]

    # 普通新闻按 News Value Score 排序
    # 当前使用 headline selection 阶段 LLM 给出的 score 作为临时排序依据。
    # 未来加入主题版块后，将重新设计 Ordinary 的分类、排序和版块配额机制。
    headline_score_map = {}
    for h in headlines_result:
        idx = h["item_index"]
        if 1 <= idx <= len(group_representatives):
            _, grp = group_representatives[idx - 1]
            headline_score_map[grp.group_id] = h["score"]

    ordinary_scored = []
    unscored_count = 0
    for item in ordinary_candidates:
        grp = item_to_group.get(id(item))
        if grp and grp.group_id in headline_score_map:
            ordinary_scored.append((item, headline_score_map[grp.group_id]))
        else:
            unscored_count += 1
            ordinary_scored.append((item, 0))

    if unscored_count > 0:
        logger.info(f"普通新闻中有 {unscored_count} 条无 score（来自非 headline group 或无 group），以 score=0 排序")

    ordinary_scored.sort(key=lambda x: x[1], reverse=True)
    ordinary_items = [item for item, _ in ordinary_scored]

    # 普通新闻上限 40 条
    MAX_ORDINARY = 40
    if len(ordinary_items) > MAX_ORDINARY:
        logger.info(f"普通新闻超过 {MAX_ORDINARY} 条上限，截断")
        ordinary_items = ordinary_items[:MAX_ORDINARY]

    logger.info(f"头版: {len(selected_groups)} groups, 普通: {len(ordinary_items)} 条")
    logger.info(
        f"总计: {len(selected_groups) + len(ordinary_items)} / "
        f"{len(deduped_items)} 条"
    )

    # 翻译所有新闻：每条 headline group 只翻译 leader；ordinary 翻译全部
    t_phase = time.time()
    headlines_rep_items = [g.leader for g in selected_groups]
    all_items_to_translate = headlines_rep_items + ordinary_items
    all_translated = []
    if all_items_to_translate:
        logger.info(f"通过 Windows Python 调用 Google Translate 翻译 {len(all_items_to_translate)} 条新闻...")
        all_translated = _call_windows_translate(all_items_to_translate)
        if not all_translated:
            logger.warning("Windows 翻译失败，使用原始标题")
            all_translated = []
    timings.append(("Google Translate (Windows)", time.time() - t_phase))

    # 构造翻译索引（item_index → translated dict）
    translate_map = {t["item_index"]: t for t in all_translated}

    # 构造 rep_items 的 item_index 映射（用于查找 group leader 的翻译）
    rep_item_index = {}
    for i, (rep, _) in enumerate(group_representatives):
        rep_item_index[id(rep)] = i + 1

    # 构造头条数据（group 级别，一个 group = 一个 headline card）
    headline_data = []
    for group in selected_groups:
        leader = group.leader
        leader_idx = rep_item_index.get(id(leader))
        tr = translate_map.get(leader_idx, {}) if leader_idx else {}
        entry = {
            "title": leader.title,
            "title_zh": tr.get("title_zh", leader.title),
            "summary": leader.summary,
            "summary_zh": tr.get("summary_zh", ""),
            "sources": leader.sources,
            "language": leader.language,
            "group_id": group.group_id,
            "group_type": group.group_type,
        }
        if leader.image_url:
            entry["image_url"] = leader.image_url
        if group.group_type == "related":
            entry["group_members"] = [
                {
                    "title": m.title,
                    "title_zh": "",
                    "summary": m.summary,
                    "summary_zh": "",
                    "sources": m.sources,
                    "language": m.language,
                }
                for m in group.items if m is not leader
            ]
        headline_data.append(entry)

    # 构造普通新闻数据（含 group 信息）
    ordinary_data = []
    headline_count = len(selected_groups)
    for j, item in enumerate(ordinary_items, 1):
        i = headline_count + j  # item_index 在 combined list 中的位置
        tr = translate_map.get(i, {})
        group = item_to_group.get(id(item))
        entry = {
            "title": item.title,
            "title_zh": tr.get("title_zh", item.title),
            "summary": item.summary,
            "summary_zh": tr.get("summary_zh", ""),
            "sources": item.sources,
            "language": item.language,
        }
        if item.image_url:
            entry["image_url"] = item.image_url
        if group and group.group_type != "single":
            entry["group_id"] = group.group_id
            entry["group_type"] = group.group_type
            if group.group_type == "related":
                entry["group_members"] = [
                    {"title": m.title, "source_names": m.source_names}
                    for m in group.items if m is not item
                ]
        ordinary_data.append(entry)

    # ============================================================
    # 7. 格式化输出
    # ============================================================
    t_phase = time.time()
    logger.info("正在生成 Markdown 简报...")

    output_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        output_config.get("dir", output_dir),
    )
    filename_template = output_config.get("filename", "newsletter_YYYY-MM-DD.md")

    filepath = format_newsletter(
        newsletter_data=ordinary_data,
        output_dir=output_path,
        filename_template=filename_template,
        sections_config=sections,
        date=date,
        headlines=headline_data,
    )
    timings.append(("输出 Markdown", time.time() - t_phase))

    # ============================================================
    # 7.5 输出 JSON（供 HTML 生成器使用）
    # ============================================================
    t_phase = time.time()
    json_path = os.path.join(output_path, "selected_news.json")
    json_data = {
        "headlines": headline_data,
        "ordinary": ordinary_data,
        "total_raw": dedup_stats["input_count"],
        "total_groups": dedup_stats["output_count"],
        "dedup_stats": dedup_stats,
        "news_groups_summary": [
            {
                "group_id": g.group_id,
                "group_type": g.group_type,
                "member_count": len(g.items),
                "leader_title": g.leader.title,
            }
            for g in news_groups
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json_module.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 数据已保存到 {json_path}")
    timings.append(("输出 JSON", time.time() - t_phase))

    # ============================================================
    # 耗时汇总
    # ============================================================
    total_time = time.time() - t_total
    timings.append(("总耗时", total_time))

    logger.info("=" * 50)
    logger.info("耗时统计:")
    for name, secs in timings:
        if secs >= 60:
            logger.info(f"  {name:20s}  {secs/60:.1f} 分钟 ({secs:.1f} 秒)")
        else:
            logger.info(f"  {name:20s}  {secs:.1f} 秒")
    logger.info("=" * 50)
    logger.info(f"简报生成完成: {filepath}")
    logger.info("=" * 50)

    return filepath
