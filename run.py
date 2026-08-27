#!/usr/bin/env python3
"""
私人新闻简报 - 命令行入口

用法：
    python run.py                    # 生成今天的简报（当天已有缓存则 resume）
    python run.py --date 2026-08-18  # 指定日期
    python run.py --config ./my-config  # 使用自定义配置目录
    python run.py --force-refresh    # 忽略当天缓存，重新执行完整 pipeline

    # 两阶段运行：
    python run.py --raw-file data/raw_news.json       # 仅获取，保存 JSON
    python run.py --load-raw data/raw_news.json        # 从 JSON 继续处理

缓存说明：
    缓存目录 cache/YYYY-MM-DD/（raw_news / dedup_groups / ranking / translation）。
    当天缓存完整时默认 resume（完整复用当天 RSS/评分/翻译缓存，仅重新生成输出，
    翻译成功率只作质量指标展示，不影响复用）。
    --force-refresh 删除当天缓存并完整重跑。不做跨日期复用。
    --retranslate-only（预留独立操作）：复用 raw/dedup/ranking 缓存，仅重新翻译。
"""

import argparse
import logging
import sys
import os

# Windows 控制台 UTF-8 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 确保 src 目录在 Python 路径中
sys.path.insert(0, os.path.dirname(__file__))

from src.main import run


def main():
    parser = argparse.ArgumentParser(
        description="私人新闻简报 - 每日新闻获取、筛选、摘要生成工具"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="指定日期（格式：YYYY-MM-DD），默认为今天",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config",
        help="配置文件目录路径（默认：config）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="输出目录路径（默认：output）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="指定 LLM 模型（格式：provider/model）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志",
    )
    parser.add_argument(
        "--raw-file",
        type=str,
        default=None,
        help="执行获取后将原始新闻保存到此 JSON 文件（不执行后续处理）",
    )
    parser.add_argument(
        "--load-raw",
        type=str,
        default=None,
        help="从 JSON 文件加载原始新闻，跳过获取阶段",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="忽略当天缓存，删除缓存目录并重新执行完整 pipeline（重新抓取/评分/翻译）",
    )
    parser.add_argument(
        "--retranslate-only",
        action="store_true",
        help="预留独立操作：复用当天 raw/dedup/ranking 缓存，仅重新翻译新闻并覆盖翻译缓存",
    )

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # 运行
    filepath = run(
        config_dir=args.config,
        output_dir=args.output,
        date=args.date,
        model=args.model,
        raw_file=args.raw_file,
        load_raw=args.load_raw,
        force_refresh=args.force_refresh,
        retranslate_only=args.retranslate_only,
    )

    if filepath:
        print(f"\n简报已保存到: {filepath}")
        sys.exit(0)
    else:
        print("\n简报生成失败，请查看上方日志", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
