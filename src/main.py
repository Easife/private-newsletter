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
import shutil
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
from . import cache as cache_store

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


def _call_windows_translate(
    items: list[NewsItem],
    timeout: int = 600,
    translation_config: Optional[dict] = None,
) -> list:
    """通过 Windows Python 调用 Google Translate

    流程：
    1. 序列化 items 到 JSON（item_index = combined list 中的1-based 索引）
    2. 写入 Windows 端 input 文件（使用 Windows 路径）
    3. 调用 Windows Python 运行 translate_news_windows.py
    4. 读取 Windows 端 output 文件

    Args:
        items: 待翻译新闻
        timeout: 整个 Windows 翻译进程的超时（秒）
        translation_config: config/newsletter.yaml 的 translation 段，
            用于透传 Google 分批大小/批间延迟、Bing 快速失败参数
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

    # 3. 调用 Windows Python（使用 Windows 路径；根据配置透传参数）
    cmd = [
        WIN_PYTHON, WIN_TRANSLATE_SCRIPT_WIN,
        "--input", input_path_win,
        "--output", output_path_win,
    ]
    cfg = translation_config or {}
    g_cfg = cfg.get("google", {}) or {}
    b_cfg = cfg.get("bing", {}) or {}
    if g_cfg.get("batch_size"):
        cmd += ["--batch-size", str(g_cfg["batch_size"])]
    if g_cfg.get("batch_delay_min") is not None:
        cmd += ["--batch-delay-min", str(g_cfg["batch_delay_min"])]
    if g_cfg.get("batch_delay_max") is not None:
        cmd += ["--batch-delay-max", str(g_cfg["batch_delay_max"])]
    if b_cfg.get("timeout") is not None:
        cmd += ["--bing-timeout", str(b_cfg["timeout"])]
    if b_cfg.get("max_fail_streak") is not None:
        cmd += ["--bing-max-fail-streak", str(b_cfg["max_fail_streak"])]

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


def _build_translation_models(
    cli_model: Optional[str],
    translation_config: Optional[dict],
) -> list[str]:
    """LLM 翻译模型 fallback 顺序（最多 5 个）

    - 若命令行指定 --model：插到最前（显式指定优先）
    - 其余来自 config translation.llm.model_fallbacks（优先 OpenCode 免费模型）
    - 去重，最多 5 个
    """
    fallbacks: list = []
    if translation_config:
        llm_cfg = translation_config.get("llm", {}) or {}
        fallbacks = llm_cfg.get("model_fallbacks") or []
    models: list[str] = []
    if cli_model:
        models.append(cli_model)
    for m in fallbacks:
        if m and m not in models:
            models.append(m)
    return models[:5]


def _call_windows_translate_with_fallback(
    items: list[NewsItem],
    model: Optional[str] = None,
    timeout: int = 900,
    translation_config: Optional[dict] = None,
    llm_usage: Optional[dict] = None,
) -> list:
    """翻译三层 fallback：Google Translate → Bing（快速失败）→ LLM（多模型 fallback）

    第一层：Windows Python 调用 Google Translate（如启用 Bing 则先 Google 后 Bing）。
    第三层：仍失败的条目交给 LLM 批量翻译，按 config 中的 model_fallbacks 顺序、
    前一个模型失败后自动尝试下一个（最多 5 个模型，均在 OpenCode 可用范围内）。
    三层都失败：保留英文原文（title_zh = title, summary_zh = 原文或空）。

    Args:
        items: 待翻译新闻
        model: CLI 指定的模型（若有，作为翻译首要模型）
        timeout: Windows 翻译进程超时（秒）
        translation_config: config translation 段（Google/Bing 参数 + LLM 模型顺序）
        llm_usage: 可选 dict，函数填充各 LLM 模型的实际使用统计

    保持数据结构不变（各 layer 只填充 title_zh / summary_zh）。
    """
    # 第一、二层：Windows 端 Google + Bing
    results = _call_windows_translate(items, timeout=timeout, translation_config=translation_config)

    if not results:
        logger.warning("Windows 翻译（Google+Bing）整体失败，全部条目交给 LLM fallback")
        results = [
            {
                "item_index": i,
                "title_zh": item.title,
                "summary_zh": item.summary,
                "err_title": "WINDOWS_FAIL",
                "err_summary": "WINDOWS_FAIL",
            }
            for i, item in enumerate(items, 1)
        ]

    # 检查哪些条目翻译失败（err 非空）
    failed_indices = []
    for entry in results:
        if entry.get("err_title") or entry.get("err_summary"):
            failed_indices.append(entry.get("item_index"))

    if not failed_indices:
        logger.info("翻译第一层（Google/Bing）全部成功，无需 fallback")
        return results

    logger.info(f"翻译第二层（LLM）: 处理 {len(failed_indices)} 条失败条目...")

    # 收集失败条目对应的 NewsItem（item_index 是 combined list 中的 1-based）
    failed_items = []
    for idx in failed_indices:
        if isinstance(idx, int) and 1 <= idx <= len(items):
            failed_items.append(items[idx - 1])

    if not failed_items:
        logger.warning("失败条目索引无效，跳过 LLM fallback")
        return results

    # 调用 LLM 批量翻译（src.llm.translate_ordinary_news，支持多模型 fallback）
    try:
        from .llm import translate_ordinary_news as llm_translate
        models = _build_translation_models(model, translation_config or {})
        logger.info(f"LLM 翻译模型 fallback 顺序: {', '.join(models) or 'opencode 默认'}（最多 5 个，失败的模型将自动跳过替换为下一个）")
        llm_results = llm_translate(failed_items, models=models, model_usage=llm_usage)
    except Exception as e:
        logger.error(f"LLM 翻译调用异常: {e}")
        llm_results = None

    if not llm_results:
        logger.warning("LLM 翻译失败，保留英文原文")
        return results

    # 将 LLM 翻译结果合并回 results
    # LLM 的 item_index 是 failed_items（子列表）中的 1-based 位置，
    # 对应 failed_indices 中相同位置的原始 item_index。
    llm_map = {}
    for tr in llm_results:
        local_idx = tr.get("item_index")
        if isinstance(local_idx, int) and 1 <= local_idx <= len(failed_indices):
            orig_index = failed_indices[local_idx - 1]
            llm_map[orig_index] = tr

    merged = []
    for entry in results:
        idx = entry.get("item_index")
        if idx in llm_map:
            lu = llm_map[idx]
            # 逐字段覆盖失败项；LLM 翻译成功则清除该字段 err（让翻译成功率反映最终有效翻译）
            if entry.get("err_title"):
                entry["title_zh"] = lu.get("title_zh", entry.get("title_zh", ""))
                if entry.get("title_zh"):
                    entry["err_title"] = None
            if entry.get("err_summary"):
                entry["summary_zh"] = lu.get("summary_zh", entry.get("summary_zh", ""))
                if entry.get("summary_zh"):
                    entry["err_summary"] = None
        merged.append(entry)

    logger.info(f"LLM fallback 完成: {len(llm_map)} 条合并，共 {len(merged)} 条")
    return merged


def run(
    config_dir: str = "config",
    output_dir: str = "output",
    date: Optional[str] = None,
    model: Optional[str] = None,
    raw_file: Optional[str] = None,
    load_raw: Optional[str] = None,
    force_refresh: bool = False,
    retranslate_only: bool = False,
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

    缓存：
    - 每日独立 run，缓存保存在 cache/YYYY-MM-DD/ 下
    - 若当天缓存完整且未传 force_refresh：resume 模式。
      完整复用当天 RSS/评分/翻译缓存，不论翻译成功率高低，
      只重新生成 selected_news 和 HTML（翻译成功率仅作质量指标展示，
      不改变 resume 的复用语义）。
    - force_refresh=True：删除当天缓存，从 RSS 抓取开始完整重跑
    - retranslate_only=True（预留的独立操作，本次不影响正常 resume）：
      复用 raw/dedup/ranking 缓存，仅重新翻译当天新闻，直接覆盖翻译缓存。

    Args:
        config_dir: 配置文件目录
        output_dir: 输出目录
        date: 指定日期（YYYY-MM-DD），默认今天。用于筛选新闻和输出文件名。
        model: LLM 模型选择（评分使用；翻译优先使用配置中的免费模型 fallback 列表）
        raw_file: 执行 fetch 后将原始新闻保存到此 JSON 文件（不执行后续处理）
        load_raw: 从 JSON 文件加载原始新闻，跳过 fetch 阶段
        force_refresh: 忽略当天缓存，重新执行完整 pipeline
        retranslate_only: 仅重新翻译（预留独立操作），复用 raw/dedup/ranking 缓存

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

    # 缓存：cache/YYYY-MM-DD/
    project_root_str = str(PROJECT_ROOT)
    cache_day_dir = cache_store.cache_dir(project_root_str, date)
    resume_mode = False
    reuse_stage = False
    if force_refresh:
        # 刷新：删除当天缓存，完整重跑
        if cache_store.is_complete(cache_day_dir) or os.path.isdir(cache_day_dir):
            cache_store.delete(cache_day_dir)
            logger.info(f"--force-refresh: 已删除缓存 {cache_day_dir}")
    elif cache_store.is_complete(cache_day_dir):
        stat = cache_store.load_translation_stats(cache_day_dir)
        rate = stat.get("success_rate", 1.0)
        if retranslate_only:
            # 预留独立操作：复用 raw/dedup/ranking，仅重新翻译
            reuse_stage = True
            logger.info(
                f"--retranslate-only: 复用 raw/dedup/ranking 缓存，仅重新翻译"
                f"（翻译质量 {rate:.0%}，仅作参考）"
            )
        else:
            resume_mode = True
            logger.info(
                f"检测到当天缓存 {cache_day_dir}，进入 resume 模式："
                f"完整复用 RSS/评分/翻译缓存（翻译质量 {rate:.0%}，仅作质量指标展示，"
                f"不影响复用），只重新生成 selected_news 和 HTML"
            )

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
    selection_config = newsletter_config.get("selection", {})
    translation_config = newsletter_config.get("translation", {})

    # 头版/普通新闻数量（来自配置 selection 段）
    # 原设计: rank 1-10 = 重要, rank 11-50 = 普通(40 条), rank 51-60 = backup(10 条)
    headline_count = selection_config.get("headline_count", 10)
    candidate_count = selection_config.get("candidate_count", 60)
    max_ordinary = headline_count * 4  # rank 11-50 = 40 条，剩余 51-60 进入 backup

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

    # 预定义变量（resume 时由缓存填充；完整流程时由各阶段填充）
    news_groups: list = []
    deduped_items: list = []
    dedup_stats: dict = {}
    candidates_result: list = []
    all_translated: list = []

    if not (resume_mode or reuse_stage):
        # ============================================================
        # 2. RSS 抓取 / 加载
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

        # 缓存：保存原始新闻（供 resume 完整校验）
        cache_store.save_raw(all_items, cache_day_dir)
        logger.info(f"原始新闻已缓存: {cache_day_dir}")

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

        # 缓存：保存去重结果
        cache_store.save_dedup_groups(news_groups, deduped_items, dedup_stats, cache_day_dir)
        logger.info(f"去重结果已缓存: {cache_day_dir}")

        # ============================================================
        # 5. LLM 评分排序（group 级别，候选池 60 条）
        # ============================================================
        # 原设计：
        #   dedup → 全部 group 代表 → LLM 依据权重参考表评分
        #   → 返回最多 candidate_count 条候选 {id, score}
        #   → Python 本地按 score 降序
        #   → rank 1-10 = 今天重要新闻, rank 11-50 = 今日普通新闻, rank 51-60 = backup
        # score 只存在于临时 selection 结果，不写入最终新闻数据。
        t_phase = time.time()
        logger.info("第一轮 LLM: 候选池评分...")

        # 构建 group 代表列表：每个 group 只选一条代表送 LLM
        group_representatives = []  # [(representative_item, NewsGroup)]
        for g in news_groups:
            if g.group_type == "related":
                rep = max(g.items, key=lambda x: len(x.sources))
                group_representatives.append((rep, g))
            else:
                group_representatives.append((g.leader, g))

        rep_items = [rep for rep, g in group_representatives]
        rep_group_ids = [g.group_id for _, g in group_representatives]

        candidates_result = select_headlines(
            items=rep_items,
            model=model,
            candidate_count=candidate_count,
            group_ids=rep_group_ids,
            models=_build_translation_models(model, translation_config),
        )

        if not candidates_result:
            logger.error("候选池评分失败")
            return None

        logger.info(f"候选池评分完成: {len(candidates_result)} 条候选人")
        timings.append(("候选池评分 (LLM)", time.time() - t_phase))

        # 缓存：保存评分结果
        cache_store.save_ranking(candidates_result, cache_day_dir)
        logger.info(f"评分结果已缓存: {cache_day_dir}")
    else:
        # resume 模式（高质量或低质量重翻）：从缓存恢复全部中间产物
        t_phase = time.time()
        news_groups, deduped_items, dedup_stats = cache_store.load_dedup_groups(cache_day_dir)
        candidates_result = cache_store.load_ranking(cache_day_dir)
        if reuse_stage:
            logger.info(
                f"retranslate-only: 恢复 {len(news_groups)} 组, {len(candidates_result)} 条评分, "
                f"{dedup_stats.get('input_count', 0)} 条原始"
            )
        else:
            logger.info(
                f"resume 恢复: {len(news_groups)} 组, {len(candidates_result)} 条评分, "
                f"{dedup_stats.get('input_count', 0)} 条原始"
            )
        timings.append(("缓存恢复", time.time() - t_phase))

        # 重建 group 代表列表（与完整流程一致）
        group_representatives = []
        for g in news_groups:
            if g.group_type == "related":
                rep = max(g.items, key=lambda x: len(x.sources))
                group_representatives.append((rep, g))
            else:
                group_representatives.append((g.leader, g))

    # ============================================================
    # 5.5 按 score 分配 rank（Python 本地排序）
    # ============================================================
    # 候选结果已按 score 降序排列（_parse_headline_selection 排序）
    ranked_items = []
    for rank, cand in enumerate(candidates_result, 1):
        idx = cand["item_index"]  # 1-based into group_representatives
        if idx < 1 or idx > len(group_representatives):
            logger.error(f"候选 item_index {idx} 超出范围，跳过")
            continue
        rep, group = group_representatives[idx - 1]
        ranked_items.append({
            "rank": rank,
            "score": cand["score"],
            "group_id": group.group_id,
            "group_type": group.group_type,
            "rep": rep,
            "group": group,
        })

    # 分配 rank
    selected_groups = []
    ordinary_candidates_result = []
    backup_candidates = []
    for entry in ranked_items:
        if len(selected_groups) < headline_count:
            selected_groups.append(entry["group"])
        elif len(ordinary_candidates_result) < max_ordinary:
            ordinary_candidates_result.append(entry)
        else:
            backup_candidates.append(entry)

    ordinary_groups = [e["group"] for e in ordinary_candidates_result]

    logger.info(
        f"排名分配: 今天重要新闻 {len(selected_groups)} 条, "
        f"今日普通新闻 {len(ordinary_groups)} 条, "
        f"backup 备用池 {len(backup_candidates)} 条"
    )
    logger.info("=" * 40)
    logger.info("score 排序明细 (Top 60):")
    for entry in ranked_items:
        rep = entry["rep"]
        src_names = ", ".join(rep.source_names[:3]) if rep.source_names else ""
        logger.info(
            f"rank {entry['rank']:2d} | score {entry['score']:3d} | "
            f"{entry['group_id']} | {rep.title[:50]} | [{src_names}]"
        )
    logger.info("=" * 40)

    # 输出临时 ranking 结果文件（含 score，供调试；score 不写入 selected_news.json）
    ranking_debug = {
        "date": date,
        "candidate_count": candidate_count,
        "headline_count": headline_count,
        "result": [
            {
                "rank": e["rank"],
                "score": e["score"],
                "group_id": e["group_id"],
                "group_type": e["group_type"],
                "title": e["rep"].title,
                "sources": e["rep"].source_names,
                "section": "headline" if e["rank"] <= headline_count
                          else ("ordinary" if e["rank"] <= headline_count + max_ordinary else "backup"),
            }
            for e in ranked_items
        ],
    }
    ranking_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        output_config.get("dir", output_dir),
        "ranking_debug.json",
    )
    os.makedirs(os.path.dirname(ranking_path), exist_ok=True)
    with open(ranking_path, "w", encoding="utf-8") as f:
        json_module.dump(ranking_debug, f, ensure_ascii=False, indent=2)
    logger.info(f"临时 ranking 结果已保存: {ranking_path}")

    # 翻译所有新闻：每条 headline group 只翻译 leader；ordinary 翻译各 group leader
    # 三种路径：
    #   - resume 模式（resume_mode=True）：复用已有翻译缓存，不重新翻译
    #   - 预留 retranslate-only（reuse_stage=True）：复用 raw/dedup/ranking，仅重新翻译
    #   - 完整模式：抓取→去重→评分→翻译，全程写缓存
    t_phase = time.time()
    headlines_rep_items = [g.leader for g in selected_groups]
    ordinary_rep_items = [g.leader for g in ordinary_groups]
    all_items_to_translate = headlines_rep_items + ordinary_rep_items

    # LLM 翻译模型 fallback 顺序（config 免费模型列表，最多 5 个；若指定 --model 则插到最前）
    llm_usage: dict = {}
    if reuse_stage:
        # 预留独立操作：仅重新翻译，直接覆盖翻译缓存
        logger.info(
            f"[retranslate-only] 仅重新翻译 {len(all_items_to_translate)} 条"
            f"（Google 分批 + 随机间隔 → Bing 快速失败 → LLM 多模型 fallback）..."
        )
        all_translated = []
        if all_items_to_translate:
            all_translated = _call_windows_translate_with_fallback(
                all_items_to_translate, model=model,
                translation_config=translation_config, llm_usage=llm_usage,
            )
            if not all_translated:
                logger.warning("翻译失败，使用原始标题")
                all_translated = []
        cache_store.save_translation(all_translated, cache_day_dir)
        logger.info(f"[retranslate-only] 翻译已更新并写回缓存: {cache_day_dir}")
    elif resume_mode:
        # resume 模式：完整复用当天翻译缓存（不论成功率高低）
        all_translated = cache_store.load_translation(cache_day_dir)
        rate_cached = cache_store.translation_success_rate(all_translated)
        logger.info(
            f"翻译恢复（resume，完整复用）: {len(all_translated)} 条, "
            f"成功率 {rate_cached:.0%}（质量指标展示，不触发重翻）"
        )
    else:
        # 完整模式：正常翻译 + 写缓存
        all_translated = []
        if all_items_to_translate:
            logger.info(
                f"通过 Windows Python 调用 Google Translate 翻译 {len(all_items_to_translate)} 条新闻"
                f"（Google 分批 {translation_config.get('google', {}).get('batch_size', 25)}+，"
                f"批间随机等待 → Bing 快速失败 → LLM 多模型 fallback）..."
            )
            all_translated = _call_windows_translate_with_fallback(
                all_items_to_translate, model=model,
                translation_config=translation_config, llm_usage=llm_usage,
            )
            if not all_translated:
                logger.warning("翻译失败，使用原始标题")
                all_translated = []
        cache_store.save_translation(all_translated, cache_day_dir)
        logger.info(f"翻译结果已缓存: {cache_day_dir}")
        logger.info(f"翻译质量: {cache_store.translation_success_rate(all_translated):.0%}")
    # LLM 翻译模型使用统计（最终报告用：各模型翻译成功条数）
    for mname, rec in llm_usage.items():
        if rec.get("success_items", 0) or rec.get("attempts", 0):
            logger.info(
                f"LLM 翻译模型 | {mname} | 成功 {rec.get('success_items', 0)} 条 "
                f"/ 批次 {rec.get('success_batches', 0)} | 尝试 {rec.get('attempts', 0)} 次"
            )
    timings.append(("翻译 (Google→Bing→LLM)", time.time() - t_phase))

    # 构造翻译索引（item_index → translated dict）
    translate_map = {t["item_index"]: t for t in all_translated}

    # 构造头条数据（group 级别，一个 group = 一个 headline card）
    headline_data = []
    for h_idx, group in enumerate(selected_groups, 1):
        leader = group.leader
        # all_items_to_translate = headlines_rep_items + ordinary_rep_items，
        # 因此 headline 第 h_idx 条在 combined 列表中的 1-based 位置即为 h_idx
        tr = translate_map.get(h_idx, {}) if all_translated else {}
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

# 构造普通新闻数据（group 级别，各 group 取 leader）
    ordinary_data = []
    headline_count_actual = len(selected_groups)
    for j, group in enumerate(ordinary_groups, 1):
        item = group.leader
        i = headline_count_actual + j  # item_index 在 combined list 中的位置
        tr = translate_map.get(i, {})
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
        if group.group_type != "single":
            entry["group_id"] = group.group_id
            entry["group_type"] = group.group_type
            if group.group_type == "related":
                entry["group_members"] = [
                    {"title": m.title, "source_names": m.source_names}
                    for m in group.items if m is not item
                ]
        ordinary_data.append(entry)

    logger.info(f"今天重要新闻: {headline_count_actual} 组, 今日普通新闻: {len(ordinary_data)} 组")
    logger.info(f"总计: {len(selected_groups) + len(ordinary_data)} / {len(deduped_items)} 条")

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
    # 7.6 生成 DeepSeek HTML（pipeline 唯一正式 renderer）+ 归档
    # ============================================================
    # classic 主题 generate_real_html_v2.py 保留为备份，不参与自动流程。
    # HTML 归档：archive/YYYY-MM-DD/newsletter.html + latest/newsletter.html
    t_phase = time.time()
    logger.info("生成 DeepSeek 主题 HTML...")
    try:
        project_root = os.path.dirname(os.path.dirname(__file__))
        gen_module = os.path.join(project_root, "generate_deepseek_html.py")
        gen_raw = os.path.join(project_root, "data", "daily_run_raw.json")
        gen_pipeline_json = json_path
        gen_output = os.path.join(project_root, "prototype", "deepseek_style_output", "newsletter.html")

        # 直接调用渲染器（同进程内导入，复用其 render()）
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("generate_deepseek_html", gen_module)
        gds = _ilu.module_from_spec(spec)
        spec.loader.exec_module(gds)
        rc = gds.render(gen_pipeline_json, gen_raw, gen_output, verbose=False)
        if rc != 0:
            logger.warning("DeepSeek HTML 生成失败")
        else:
            logger.info(f"DeepSeek HTML 已生成: {gen_output}")

            # HTML 归档（日期目录 + 最新版）
            archive_day = os.path.join(project_root, "archive", date, "newsletter.html")
            os.makedirs(os.path.dirname(archive_day), exist_ok=True)
            shutil.copy2(gen_output, archive_day)
            logger.info(f"HTML 已归档: {archive_day}")

            latest_dir = os.path.join(project_root, "latest")
            os.makedirs(latest_dir, exist_ok=True)
            shutil.copy2(gen_output, os.path.join(latest_dir, "newsletter.html"))
            logger.info(f"HTML 最新版已更新: {os.path.join(latest_dir, 'newsletter.html')}")
    except Exception as e:
        logger.error(f"DeepSeek HTML 生成异常: {e}")
    timings.append(("生成 DeepSeek HTML", time.time() - t_phase))

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
