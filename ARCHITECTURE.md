# 私人新闻简报 - 项目架构

## 1. 项目目标

一个独立运行的每日新闻简报生成工具。获取当天重要新闻，结合用户兴趣筛选、去重、摘要，生成一份简洁的 Markdown 简报，帮助用户在 5-10 分钟内知道今天值得知道的事情。

核心原则：少而精，宁缺毋滥。

## 2. 程序组成

```
run.py（CLI 入口）
    │
    ▼
src/main.py（管道调度）
    │
    ├── config/*.yaml（配置文件，程序不修改）
    │
    ├── src/fetcher.py（新闻获取层）
    │       读取 sources.yaml，并发抓取 RSS feeds
    │       输出：[NewsItem, ...]（每个 NewsItem 包含 sources 列表）
    │
    ├── main.py 内置日期筛选
    │       按 --date 参数筛选目标日期的新闻
    │
    ├── src/dedup.py（去重与事件聚类）
    │       标题相似度去重，同一事件多源合并
    │       合并后保留所有来源的名称、URL 和权重
    │       输出：去重后的 [NewsItem, ...]
    │
    ├── src/llm.py（LLM 调用层）
    │       构造 prompt → 调用 opencode run → 解析 JSON 输出
    │       完成：评分 + 分区 + 摘要生成
    │       注意：LLM 不生成 URL，URL 始终来自原始 NewsItem
    │       输出：处理后的新闻列表（LLM 元数据 + 原始来源信息）
    │
    └── src/formatter.py（Markdown 格式化）
            将结构化数据转为 Markdown 文件
            输出：output/newsletter_YYYY-MM-DD.md
```

## 3. 新闻从哪里获取

第一阶段通过 RSS feeds 获取。RSS 是多数主流新闻机构提供的标准化订阅格式，无需登录、无反爬限制。

fetcher.py 被设计为"新闻发现与获取层"，RSS 只是第一阶段的实现方式。未来可扩展：
- 搜索引擎 API（如 Google News API）
- 新闻聚合 API（如 NewsAPI）
- 网页抓取（需要时作为兜底）
- 官方来源直接对接

每个来源在 sources.yaml 中配置，包含名称、RSS URL、权重和语言标签。

## 4. 新闻如何筛选

筛选分三步：

**第一步：日期筛选（main.py）**
- 按 --date 参数筛选目标日期的新闻
- 能解析日期的条目只保留日期匹配的
- 无法解析日期的条目保留（宁多勿漏）

**第二步：本地去重（dedup.py）**
- 基于标题关键词的 Jaccard 相似度
- 超过阈值（默认 0.6）的条目合并为同一事件
- 合并后保留所有来源的名称、URL 和权重

**第三步：LLM 筛选和排序（llm.py）**
- 将去重后的所有新闻一次性提交给 LLM
- LLM 根据用户兴趣和客观重要性进行评分和分区

## 5. 如何判断新闻重要性

第一阶段不使用独立的评分算法，而是让 LLM 综合判断。LLM 在 prompt 中被告知：
- 用户的长期兴趣列表
- 用户的近期关注列表
- 四个分区的定义和规则

LLM 为每条新闻输出一个 0-100 的分数（score），并分配到对应分区。

评分依据（在 prompt 中指导 LLM）：
- 客观重要性：战争、灾难、金融事件、重大政策等
- 用户兴趣匹配：是否与长期兴趣相关
- 新颖性：是否是新事件还是已有事件的后续

注意：来源权重（source_weight）仅在本地去重合并时用于选择主来源，不传递给 LLM。
LLM 的评分完全基于新闻内容本身。

## 6. 如何结合用户兴趣

用户兴趣在 interests.yaml 中配置，分为两类：

- `long_term`：长期关注的领域（如 AI、中美关系等），持续影响筛选
- `recent`：最近几天特别关注的事件，短期优先级更高

这两个列表作为上下文传给 LLM，让 LLM 在评分时参考。

## 7. 如何去重

当前实现（MVP）：
1. 将标题分词为关键词集合（英文按空格分词，中文做 2-4 gram）
2. 计算任意两条新闻标题的 Jaccard 相似度
3. 超过阈值的聚类为同一事件
4. 合并为一条新闻，所有来源的名称、URL 和权重保存在 NewsItem.sources 列表中
5. 最终简报中每个来源独立渲染为可点击的链接

未来可升级为 embedding 语义相似度，提高精度。

## 8. 如何交叉验证

当前实现：去重时记录同一事件的所有来源。如果一条新闻有多个来源，在简报中每个来源独立显示链接。

未来可增强：显式标注"已交叉验证（N 个独立来源）"。

## 9. 如何生成最终简报

1. LLM 返回 JSON 格式的结构化数据（每条新闻包含 item_index、score、category、what_happened、why_matters）
2. 程序通过 item_index 将 LLM 输出与原始 NewsItem 匹配，获取真实的来源和 URL
3. formatter.py 按 category 分组，每组按 score 降序排列
4. 每组取前 N 条（由 newsletter.yaml 的 max_items 控制）
5. 每个来源独立渲染为 Markdown 链接
6. 写入 output/ 目录

重要：URL 和来源信息始终来自 RSS 获取层的原始数据，不由 LLM 生成或猜测。

## 10. 配置文件

| 文件 | 作用 |
|------|------|
| `config/sources.yaml` | 新闻来源列表：RSS URL、权重、语言、分类标签 |
| `config/interests.yaml` | 用户长期兴趣 + 近期关注主题 |
| `config/newsletter.yaml` | 简报分区设置、条数上限、语言偏好、去重阈值 |

所有配置与程序逻辑分离，修改配置无需改代码。

## 11. 安全考虑

新闻标题和摘要是不可信的外部数据。prompt 中包含防注入声明，
明确告知 LLM 新闻内容中的任何指令都不能覆盖系统任务要求。

## 12. 未来扩展路径

**自动定时运行：**
- 用 cron job 或 systemd timer 每天定时调用 `python run.py`
- 不依赖 OpenCode 的 TUI 环境

**消息推送：**
- Telegram Bot：读取生成的 Markdown，通过 Bot API 发送
- 邮件：用 SMTP 发送 HTML 格式的简报
- 微信：通过企业微信 Webhook 推送

**与 OpenCode 解耦：**
- 当前通过 `subprocess` 调用 `opencode run`，本质上是一个外部 CLI 工具
- 未来可直接调用 OpenAI/Claude API，完全不需要 OpenCode
- llm.py 中的 `call_opencode` 函数是唯一的 OpenCode 依赖点

**长期演进：**
- 替换去重算法为 embedding 相似度
- 添加新闻来源自动发现
- 添加简报历史对比（与昨天的新闻做 diff）
- 添加简单的 Web 前端查看历史简报
