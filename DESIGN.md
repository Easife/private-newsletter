# Private Newsletter 设计与维护指南

本文解释程序解决的问题、整体数据流、模块职责、完整与增量运行、评分和翻译策略、配置边界以及修改时需要维持的不变量。面向接手维护的开发者和希望理解内部逻辑的高级用户。

## 1. 设计目标

程序要在一台 Windows 电脑上自动生成可审计的每日新闻简报，同时满足：

1. 网络抓取、AI 调用、翻译、渲染和归档由一个 Python 总调度器管理。
2. 不依赖 WSL，不要求 OpenCode 图形界面保持打开。
3. AI 只做规则难以可靠完成的内容判断，尽量减少免费 token 消耗。
4. 新闻、事件、AI 响应和译文全部通过稳定 ID 关联，不依赖列表位置。
5. 同日重复运行只处理全新事件，旧事件不重复评分和翻译。
6. 失败不发布半成品，成功版本从不覆盖。
7. 用户可以通过本机网页修改常用设置，但不能通过网页改写任意文件或命令。

## 2. 运行边界

```text
运行每日新闻.cmd
  └─ Windows Python 虚拟环境
      ├─ 本机控制台 http://127.0.0.1:8765
      ├─ RSS / Google News 抓取
      ├─ 规则过滤与事件聚类
      ├─ opencode run（无界面 CLI）
      ├─ Google GTX 翻译
      ├─ HTML / Markdown / JSON 渲染
      └─ runs / archive / latest 原子发布
```

控制台与新闻管线运行在同一个 Python 项目中，但职责分离：控制台只负责状态、输入校验和触发；管线负责业务数据。Web 服务固定绑定 `127.0.0.1`，不设计远程账户、远程访问或多用户权限。

## 3. 完整数据流

### 3.1 Fetch

`newsletter.fetch` 读取 `config/sources.yaml`，并发抓取直接 RSS 或 Google News RSS。每条记录标准化为 `NewsItem`，包含稳定 `item_id`、原标题、摘要、时间、语言、来源和图片。

抓取结果确定性排序后写入 `01_raw.json`。来源失败单独记录；只要仍有可用新闻，其他来源继续运行。

### 3.2 Filter

`newsletter.filtering` 以实际启动时刻为终点，根据配置保留过去 N 小时，默认24小时。它同时处理：

- 无时间项目策略；
- 过短标题；
- 已知聚合页、周末节目、导航类和非新闻标题；
- 时区归一化。

指定 `--date` 只控制业务日期和归档位置，不把窗口改成自然日，也不会在无结果时偷偷退回全部新闻。

### 3.3 Deduplicate

`newsletter.dedup` 根据标题 token 的 Jaccard 相似度执行代表项贪心聚类，避免 Union-Find 的传递链把多个事件无限串联。

- 单条：`single`
- 高于精确阈值：`exact_match`
- 高于相关阈值但未达到精确阈值：`related`

leader 根据来源权重、摘要完整度、时间和稳定 ID 确定。`event_id` 由组内所有 `item_id` 排序后哈希生成。

### 3.4 Candidate pool

`newsletter.ranking.build_candidate_pool` 将可能数百个事件缩小到默认60个。规则服务于召回和覆盖，不是最终编辑排名：

- 多来源事件优先；
- 每个活跃来源保留最低审阅机会；
- 单一来源通常不超过配置上限；
- 少量兴趣保留位；
- 少量来源平衡通配位；
- 剩余按只用于候选构造的规则分补齐。

RSS 和 Google News 的原始排列位置不参与候选或重要性判断。`candidate_audit.json` 保存每个事件入选或落选候选池的原因。

### 3.5 AI selection

AI 请求中每个事件只有：

```text
event_id
title
summary（最多300字符）
```

媒体名称、媒体权重、来源数量、规则分、时间戳和来源配置标签不发送给 AI，避免重复计算本地权重。兴趣列表在整次请求中只出现一次。

默认返回：

- 严格有序、带0–100重要性分数的 Top15；
- 从其余候选选择的25个事件 ID，返回顺序没有排名含义；
- 不返回兴趣分、置信度或编辑理由。

响应使用 JSON Schema，并再次验证未知 ID、重复 ID、数量和分数范围。

### 3.6 Local score adjustment

AI 分数只对 Top15 做本地校正：

```text
P = clamp((W - W₀) / (W₁ - W₀), 0, 1)
F = F₀ + ΔF × P
S = min(100, I × F + B)
```

`W` 是事件中最高媒体权重，`P` 是映射位置，`F` 是来源乘数，`B` 是多来源加分。默认参数：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| W₀ | 0.65 | 权重映射起点 |
| W₁ | 0.90 | 权重映射终点 |
| F₀ | 0.90 | 最低来源乘数 |
| ΔF | 0.10 | 来源乘数最大增幅 |
| B₂ | 2 | 两个独立来源 |
| B₃ | 4 | 三个独立来源 |
| B₄ | 6 | 四个及以上独立来源 |

校正后前10条成为头条，第11–15条位于普通新闻前五条，其余25条以数据集确定性种子打乱。普通新闻序号只表示展示顺序。

### 3.7 Translation

`newsletter.translation` 的正常路径是 Google GTX：

- GTX 标题成功：直接采用，不做机械术语拦截。
- GTX 摘要成功：直接采用。
- 摘要失败：留空，不调用 AI。
- 任意标题失败：执行一次 OpenCode 请求，补译全部失败标题，并检查当次 Top10 GTX 译文是否有严重语义错误。
- OpenCode 标题仍失败：该事件退出选择，用储备项或旧事件补位。

只翻译最终需要展示的事件及相关报道，不预翻译储备池。

### 3.8 Render and publish

`newsletter.render` 从事件、排名和译文构造统一 JSON，再生成 Markdown 和 HTML。渲染器负责：

- HTML 转义与安全 URL；
- 免费来源绿色标记；
- 付费来源红色标记并添加 Google 搜索；
- 精确合并来源不重复显示 leader；
- 相关报道独立列出但不重复主报道；
- 普通新闻固定卡片高度与文本截断。

`newsletter.pipeline._publish` 为每天分配 `newsletter-YYYYMMDD-N`，先写归档文件，最后原子更新 `latest/current.json`。任何已存在的目标名称都会拒绝覆盖。

## 4. 同日增量运行

`newsletter.incremental` 只在以下条件全部满足时启用：

- 同一业务日期存在成功运行；
- 配置哈希一致；
- 应用版本一致；
- Python 业务代码指纹一致；
- 所需阶段产物完整。

否则自动完整运行。

增量过程：

1. 重新抓取、执行24小时过滤和事件聚类。
2. 读取上次 `01_raw.json` 的全部稳定 `item_id`。
3. 当前事件只要包含旧 `item_id`，就视为旧事件或旧事件的新佐证，不重复送 AI。
4. 只有组内所有条目都未出现过的事件才进入新候选池。
5. AI 对新事件动态返回最多15条有分数事件和最多25条普通事件。
6. 新的有分数事件与旧 Top15 合并后按校正分重排。
7. 被挤出 Top15 的旧/新事件、新增普通事件和旧普通事件依次补足最终40条。
8. 只翻译真正进入合并结果的新事件；旧译文直接复用。
9. 没有新事件时，AI 和 GTX 用量均为零，但仍可发布新的可追溯版本。

这一设计优先减少 token 和重复翻译。它不会因为新媒体发布了同一事件的另一篇报道就重新评分整个旧事件。

## 5. 兴趣生命周期

`config/interests.yaml` 有两个列表：

- `long_term`：持久兴趣，参与配置哈希，每次选择都使用。
- `recent`：一次性兴趣，只影响下一次成功生成，成功后由 `run_auto_pipeline` 原子清空；失败时保留。

一次性兴趣故意不参与持久配置哈希，因此它被消费后，同日下一次运行仍可使用增量基线。长期兴趣变化会改变配置哈希并触发完整运行。

## 6. 本机控制台

`newsletter.webapp` 使用 Python 标准库 `ThreadingHTTPServer`，不引入额外 Web 框架。主要接口：

| 接口 | 作用 |
|---|---|
| `GET /api/status` | 环境、模式、运行状态和增量日志 |
| `GET /api/history` | 最近20份 HTML 简报 |
| `GET /api/settings` | 可编辑设置和系统时区列表 |
| `PUT /api/settings` | 校验、备份并原子保存设置 |
| `POST /api/generate` | 在后台线程启动自动或强制完整运行 |
| `POST /api/environment/refresh` | 重新检测配置和 OpenCode |

写请求校验 Origin，正文限制为1 MB，设置 API 只接受白名单字段。它不能修改路径、执行命令、模型凭据或任意文件。

页面资源位于 `newsletter/ui/`：

- `index.html`：语义结构和所有表单字段；
- `app.css`：与简报一致的纸张白、深绿、衬线标题设计；
- `app.js`：状态轮询、日志、历史、设置、公式实时计算和来源编辑。

## 7. 模块职责

| 模块 | 责任 |
|---|---|
| `cli.py` | 命令行、日期、运行锁与上下文入口 |
| `webapp.py` | localhost 控制台、API、设置校验与运行状态 |
| `config.py` | YAML 读取、结构校验、配置哈希 |
| `fetch.py` | RSS/Google News 抓取和 NewsItem 规范化 |
| `filtering.py` | 滚动时间窗口和非新闻过滤 |
| `dedup.py` | 标题相似度、事件聚类和 leader |
| `ranking.py` | 60条候选、AI 协议、本地分数校正 |
| `translation.py` | GTX 与条件式 OpenCode 补救 |
| `pipeline.py` | 完整管线、阶段产物和发布 |
| `incremental.py` | 基线判定、新事件识别和同日合并 |
| `render.py` | 统一数据、Markdown 与 HTML |
| `opencode_client.py` | CLI 请求、结构化响应、模型回退和 token 计量 |
| `storage.py` | 运行清单、锁、指纹和原子写入 |
| `models.py` | NewsItem、EventGroup、RankedEvent、Translation 数据模型 |

## 8. 状态与恢复

每次运行创建独立 `RunContext`。`manifest.json` 记录：

- 应用版本和代码指纹；
- 配置哈希；
- 业务日期、run ID 和时间；
- 每阶段 running/complete/failed；
- 最终发布路径。

恢复仅允许相同日期、代码和配置，防止把旧排名套到新事件。`RunLock` 防止控制台、计划任务或用户重复点击并发写同一状态。

## 9. 配置与网页编辑边界

可在网页修改：

- 时区、抓取超时、并发、代理、TLS；
- 滚动窗口和最短标题；
- 聚类阈值；
- 10+30等输出数量；
- 候选池、来源保留位和 AI 返回数量；
- 来源权重映射和多来源加分；
- 新闻来源及其抓取参数；
- 长期和一次性兴趣。

模型列表、OpenCode 登录、输出路径和凭据不在网页中编辑，避免普通用户误改安全边界。高级维护者可以直接编辑 YAML，并运行 doctor 验证。

## 10. 维护不变量

修改代码时必须保持：

1. AI 与缓存只按稳定 ID 关联，禁止数组位置关联。
2. AI 输入不重复发送来源权重和本地规则分。
3. 配置或代码变化不得复用不兼容基线。
4. 失败不得更新 `latest/current.json`。
5. 发布文件不得覆盖。
6. 付费来源必须保留来源链接和 Google 搜索链接。
7. 新增 UI 字段必须同时更新读取、校验、保存、文档和测试。
8. 新闻文本始终是不可信数据，不得成为模型或程序指令。

## 11. 扩展建议

### 添加新媒体字段

同时更新 `config.load_config`、`fetch`、网页模板、`_validate_settings`、JavaScript 序列化和测试。不要只修改 HTML。

### 调整排名协议

先修改 JSON Schema，再修改验证器和合并逻辑。评估 token 时区分普通输入、输出、推理和缓存读取。

### 增加新翻译 provider

provider 必须有明确成功条件、超时、错误记录和是否触发 AI 的规则。禁止因专有名词风格差异无限回退。

### 修改事件 ID

事件 ID 影响增量识别、缓存和历史兼容。任何变更都应提升应用版本，并明确让旧基线失效。

## 12. 测试

标准测试命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check newsletter\ui\app.js
```

测试应覆盖候选数量和 AI 最小字段、10+30渲染、当日编号、增量合并、设置校验、来源新增、本机 API 和 UI 必需控件。真实管线测试需要单独授权，因为会访问外网并消耗模型 token。
