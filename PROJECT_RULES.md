# PROJECT_RULES.md — 项目长期开发规范与冻结依据

> 本文件是本项目的**最高级开发规范**和**已确认架构的冻结依据**。
> **修改任何代码之前必须通读本文件**，并严格遵守其中所有冻结原则。
>
> 与下述原则冲突的新想法，一律不得自行采用；必须先向用户提出冲突点，由用户决定是否解除冻结。
> 相关关系文档：`ARCHITECTURE.md`（架构实现说明，供参考）、`CHANGELOG.md`（版本记录）、`README.md`（快速开始）。

---

## 1. 网络工作全部放在 Windows 端（已冻结）

**这是已经确定的架构决策，不得更改。**

所有需要访问外网的工作，包括但不限于：

- RSS 抓取
- Google 翻译
- Bing 翻译
- 外部图片 / 资源访问
- 其他 HTTP/HTTPS 网络请求

全部由 **Windows Python 环境**执行（`translate_news_windows.py` 及其同类脚本）。

### 明确禁止

- 在 WSL 内直接抓 RSS
- 在 WSL 内配置代理后抓 RSS
- 让 WSL 通过 Windows localhost 代理访问外网
- 围绕 WSL 网络问题继续修改项目架构

**WSL 不承担任何网络工作。** 当前 WSL + Windows Clash 网络不通，**不再作为本项目的待解决问题**。
未来需要真实 RSS 抓取时，必须使用 Windows 侧现有网络环境。

### 已确认的技术结论（网络）

- 本项目所有 Google 翻译请求 **100% 由 Windows 端 Python**（`translate_news_windows.py`，经 WSL 以子进程调用 Windows Python 执行）发出，代理为 Windows 本机 Clash `http://127.0.0.1:7897`。
- WSL 侧（`src/llm.py` 内 `_google_translate_one` / `translate_via_google`）存在 Google 翻译代码，但**当前 pipeline 不调用**，是死代码。不要在 WSL 侧启用它。
- `src/fetcher.py` 的 `requests.get` 是 WSL 端 RSS 抓取；当前使用 `--load-raw` 跳过。若需真实抓取，抓取侧必须改为 Windows 端执行，WSL 端不发起任何外网请求。

---

## 2. 图片来源硬性规则（已冻结）

> **图片不是由 LLM 生成、搜索或匹配的。**
> **图片只允许来自对应新闻自身的 RSS 数据。**
> **Renderer 不得改变图片与新闻之间的对应关系。**
> **如果对应 RSS 新闻没有图片，则使用占位图。**
> **不允许为了提高图片覆盖率而跨新闻复用图片。**

### 具体禁止行为

- 随机复用其他新闻的图片
- 根据标题让 LLM 自己寻找图片
- 根据新闻主题从互联网搜索图片
- 从其他新闻复制图片
- 使用一个公共图片池随机分配
- 因为图片数量不足而重复分配其他新闻图片

### 数据语义

每条数据保持"一新闻一图片"对应关系，并保留来源语义：

```
image          # RSS 提供的图片 URL（可选）
image_source = rss   # 图片来源固定为 rss；未提供则无图片字段，使用占位图
```

如果数据已存在类似字段（`image_url` + 一致性由 pipeline 保证），沿用，不做大规模重构。
Render 输出必须**逐条原样使用**每条新闻自带 `image_url`，无图则占位图。

### 已确认的技术结论（图片错配）

- **故障位置：`generate_deepseek_html.py` 的 `match_image()`（约 80-107 行）。**
- 该函数在新闻没有自带图时，用**标题关键词重叠 ≥ 2** 匹配其他有图新闻的图片，并把"同 group 其他成员"的图也视为可复用，导致大量错配（本次真实运行：37 张图中仅 22 个去重 URL，9 个 URL 被多卡片复用；卡尼关税图被套到 4 条与加拿大无关的新闻上）。
- 数据链路其他阶段**均无错配**：`raw_news.json` 与 `selected_news.json` 同一标题图片 50/50 一致；`selected_news.json` 内 14 张自带图无重复。
- RSS 图片覆盖率低（本次 74/343 ≈ 22%），但这**不构成**跨新闻复用图片的理由；无图一律占位。
- 后续若修复，仅需修改 renderer 的图片处理逻辑，不得改动 fetch/dedup/scoring/translation 的已有结构。

---

## 3. URL 规则（已冻结）

- 新闻链接必须使用 RSS 获取到的**真实 article URL**。
- 禁止：LLM 编造 URL、根据标题猜 URL、自行搜索后替换原始 URL、使用假的 placeholder URL。
- HTML 中点击新闻必须能访问对应真实文章。
- 免费来源跳原文 URL；付费来源可跳 Google 搜索（当前方案，已冻结）。

---

## 4. 网页设计冻结（DeepSeek 主题）

当前生产 renderer 为 `generate_deepseek_html.py`，其视觉设计（暖灰背景 / 渐变光晕 / glass card / 18px 圆角 / 柔和阴影 / 深色模式）**已冻结**。修改时保留原视觉风格。

### 今日头条

- 10 条
- 卡片式布局
- 图片优先使用 RSS 对应图片（见第 2 节规则）
- 无图片使用占位图

### 其他重要新闻

- 40 条
- 桌面端保持**两列** grid
- 移动端只做基本响应式适配（单列），不为移动端重构桌面布局

### 桌面端

```
max-width: 1200px
```

（而不是之前的 720px，充分利用桌面屏幕空间。已确认。）

### 移动端

只要求基本适配，禁止为了移动端大规模重构桌面端布局。

### 内容来源（renderer 职责）

HTML 中的标题、摘要、来源、图片、URL 均应来自 pipeline 已生成的数据
（`output/selected_news.json` 等）。
**Renderer 的职责是展示数据，而不是重新创造数据。**

---

## 5. Pipeline 架构冻结

```
RSS
 ↓
Windows 端抓取
 ↓
日期筛选
 ↓
去重
 ↓
候选池
 ↓
LLM 评分
 ↓
10 条头条 + 40 条普通新闻
 ↓
三层翻译（Google → Bing → LLM）
 ↓
selected_news.json
 ↓
DeepSeek HTML
 ↓
archive
```

- 当前 HTML pipeline：`generate_deepseek_html.py`，继续使用。
- `classic` / `generate_real_html_v2.py`：保留作为备份，**不参与 pipeline、不自动生成、main.py 不调用**；除非用户明确要求，否则不要重新启用。

---

## 6. 缓存语义冻结

只保留两种正常模式：

### resume

- 完整复用当天已有缓存（raw / 去重 / 评分 / 翻译）。
- **禁止**因为翻译成功率低于某个阈值而自动重翻。
- 已删除的"成功率 < 90% 自动重翻"逻辑**不得重新加入**。
- 成功率仅作为质量指标展示。

### force-refresh

- 彻底重新运行：删除对应日期缓存，重新执行完整 pipeline。

### retranslate-only

- 作为独立操作。
- 只重新执行翻译相关步骤，不改变 RSS、评分和新闻选择结果。

### 附加规则

- 缓存按日期隔离（`cache/YYYY-MM-DD/`），跨天自然全新。

---

## 7. 模型 fallback 机制冻结

- 翻译和评分从配置文件（`config/newsletter.yaml` 的 `translation` 段）读取**最多 5 个模型**。
- 按照配置顺序 fallback；**优先使用 OpenCode 免费模型**。
- 前一个模型失败后再进入下一个模型。
- 单模型最多尝试 2 次。
- 必须保留 `model_usage` 统计，用于报告实际使用情况（尝试次数 / 成功批次 / 成功条数）。
- fallback 架构已冻结，禁止为了"优化"擅自改变。

---

## 8. 开发纪律

- **先遵守已经确定的架构，再解决具体问题**；不要因为发现一个问题就重新设计整个项目。
- 不要"解决一个问题、顺手重构一大片代码"。
- 遇到与冻结原则冲突的想法：先向用户提出冲突点，由用户决定是否解除冻结。
- 本文件作为长期依据；多次改动叠加时，以本文件为基准校准。

---

## 9. 本次专项诊断结论归档（2026-08-27/28）

### Google 429

- 原因：**出口 IP 被 Google 封锁（IP 级 429）**，非频率、非代码、非请求方式变化。
- 证据：出口 IP `64.118.140.40`（新加坡，AS138997 Eons Data Communications Limited，数据中心 IP）；**单条、低频请求也立即 429**；请求方式与 git 初始快照完全一致（`client=gtx`、`UA Mozilla/5.0`、同一端点、同一代理）。"更换端口"只改 Clash 本地监听，不变化出口 IP，故 429 依旧。
- 处置：不引入新网络架构、不把 Google 请求挪到 WSL。如需恢复 Google 层，应切换 Clash 节点（更换出口 IP）后以 resume 语义重测。
- 本次翻译层最终结果：Google 0 / Bing 0（Bing 快速失败按预期禁用）/ LLM 45 条全部成功 / 中文直通 5 条，中文成功率 100%。LLM 兜底按设计工作。

### 图片错配

- 原因 / 位置：`generate_deepseek_html.py` 的 `match_image()` 关键词、group 匹配会跨新闻复用图片；renderer 修改了图片与新闻的对应关系。
- 证据：三层交叉核对——raw 与 selected 50/50 一致；selected 内无重复图；HTML 内 9 个 URL 被多卡片复用（卡尼关税图 ×5 等）；错配全部来自无自带图新闻被关键词匹配补图。
- 结论：错配发生在 **HTML renderer**，不是 RSS / dedup / 评分 / 翻译 / selected_news.json。
- 冻结后修复方向：renderer 只原样使用每条新闻自带 `image_url`，无图一律占位（待用户确认后执行）。