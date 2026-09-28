# Private Newsletter 2.2.4

[中文](#中文说明) | [English](#english)

Private Newsletter is a Windows-first, locally operated daily news briefing system. It collects multilingual news, filters a rolling 24-hour window, groups reports into events, uses AI only for editorial decisions that rules cannot reliably make, translates selected stories, and publishes immutable HTML, Markdown, and JSON editions.

---

## 中文说明

### 项目简介

Private Newsletter 是一个在 Windows 本机运行的自动化每日新闻简报程序。它抓取多语言 RSS 与 Google News 来源，以运行时刻为终点过滤过去24小时新闻，合并相同事件，通过 AI 选择重要内容，使用 Google GTX 翻译，并生成10条头条加30条普通新闻的 HTML、Markdown 和 JSON 简报。

程序不依赖 WSL，也不要求打开 OpenCode 桌面客户端。日常操作通过本机网页版控制中心完成。

### 主要功能

- 一次点击完成抓取、过滤、事件合并、AI 选择、翻译、渲染和归档。
- 在本机网页查看环境检测、运行进度、即时日志、错误与成功结果。
- 当天第一次运行处理过去24小时；同日再次运行只评估新增事件。
- 每次成功生成独立版本，例如 `newsletter-20260928-1.html`，从不覆盖旧版。
- 在网页中管理新闻来源、媒体权重、候选规则、评分参数、时区、版面数量和兴趣。
- AI 输入经过压缩；媒体权重与多来源校正在本地执行，并记录模型 token。
- 控制中心只监听 `127.0.0.1`，不向局域网或互联网开放。

### 系统要求

- Windows 10 或 Windows 11。
- 能访问已配置的新闻源、Google News、Google Translate GTX 和当前 AI 后端。
- 2.2.4 的 AI 后端仍为 OpenCode CLI，需要安装 OpenCode 并完成 OpenCode Zen 登录。

不要求预先安装 Python，也不需要管理员权限。首次启动会下载经过 SHA-256 校验的便携 `uv`，在项目的 `.tools` 目录准备 Python 3.12，并创建项目 `.venv`。

安装 OpenCode：

```powershell
npm install -g opencode-ai
opencode auth login --provider opencode
```

不要把 API Key 写入项目配置、文档或 Git 仓库。凭据应交给对应客户端或安全凭据存储管理。

### 快速开始

1. 下载或克隆仓库。
2. 双击根目录的 `运行每日新闻.cmd`，不要使用“以管理员身份运行”。
3. 首次启动等待便携 Python、虚拟环境和依赖准备完成。
4. 浏览器会自动打开 `http://127.0.0.1:8765/`。
5. 检查环境状态，按需修改并保存设置。
6. 点击“生成今日简报”。

日常操作就是：**双击 `运行每日新闻.cmd` → 等待浏览器打开 → 点击“生成今日简报”**。

根目录的 `每日新闻简报控制中心.html` 是完整 UI，也可直接打开查看版式。直接打开时页面处于“静态预览”状态，因为普通浏览器不能从静态 HTML 启动 Python 后台；要生成简报必须使用启动器。浏览器使用期间请保持启动窗口打开；关闭该窗口或双击 `停止每日新闻控制中心.cmd` 都会停止本机服务。右侧历史项会由服务安全打开对应的本地 HTML 文件。

### 简报生成逻辑

当天第一次生成时，程序会：

1. 抓取所有启用来源。
2. 保留截至运行时刻的过去24小时内容。
3. 过滤非新闻、聚合页和无效标题。
4. 合并相同事件与相关报道。
5. 用本地规则构造最多60条高召回候选。
6. 向 AI 发送稳定 `event_id`、标题、精简摘要和一次兴趣清单。
7. 获取带重要性分数的 Top15，以及另外25条普通新闻。
8. 在本地应用媒体权重和多来源加分。
9. 用 GTX 翻译最终选择；仅在标题失败时调用 AI 补译并检查 Top10 严重语义错误。
10. 发布10条头条和30条普通新闻，并分配当天递增编号。

同日再次生成且代码和持久设置未变化时，程序重新抓取新闻，但只把相对于上一成功版本的全新事件交给 AI 和翻译流程。如果没有新事件，则不产生新的 AI 或 GTX 消耗。

### 来源权重公式

AI 给出基础重要性 `I`，本地程序对 Top15 应用：

```text
P = clamp((W - W0) / (W1 - W0), 0, 1)
F = F0 + deltaF * P
S = min(100, I * F + B)
```

`W` 是事件的最高媒体权重，`F` 是来源乘数，`B` 是独立来源数量加分，`S` 是最终校正分。公式和所有参数都可在控制中心查看和修改。

### 手动命令

```powershell
# 准备环境
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

# 启动控制中心
.\.venv\Scripts\python.exe -m newsletter.webapp --config .\config

# 自动模式运行一次
.\scripts\run_daily.ps1

# 强制完整运行
.\.venv\Scripts\python.exe -m newsletter run --full --config .\config

# 运行测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check newsletter\ui\app.js
```

### 输出目录

- `runs/<日期>/<run_id>/`：阶段产物、审计信息和恢复现场。
- `archive/<日期>/`：不可变 HTML、Markdown 和 JSON 简报。
- `latest/current.json`：最近一次成功发布指针。
- `logs/`：控制中心和管线日志。
- `config/backups/`：网页保存设置前的配置备份。

### 常见问题

- **首次准备失败**：检查网络能否访问 uv/Python 发布资源，然后重新双击启动器。
- **OpenCode 异常**：运行 `opencode --version` 和 `opencode auth login --provider opencode`。
- **部分来源失败**：检查网络、代理、系统时间和来源 URL；单个来源失败不会终止其他来源。
- **已有运行锁**：确认没有简报任务在运行，再执行 `.\.venv\Scripts\python.exe -m newsletter unlock --config .\config`。
- **端口8765被占用**：先运行 `停止每日新闻控制中心.cmd`，或用 `--port` 指定其他端口。

项目内部设计见 [DESIGN.md](DESIGN.md)，架构摘要见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，2.3 计划见 [ROADMAP_2.3.md](ROADMAP_2.3.md)。

---

## English

### Overview

Private Newsletter is a Windows-first automated news briefing application. It collects multilingual RSS and Google News feeds, keeps stories from the rolling 24 hours ending at run time, groups reports into events, asks an AI backend to select important stories, translates selected content with Google GTX, and publishes a 10-headline plus 30-story briefing in HTML, Markdown, and JSON.

It does not require WSL or the OpenCode desktop application. Routine operation is handled through a local web control center.

### Highlights

- One-click fetch, filtering, event grouping, AI selection, translation, rendering, and archiving.
- Local web UI for environment checks, live progress, logs, errors, results, and settings.
- A full rolling-24-hour run for the first edition of the day; incremental processing for later same-day editions.
- Immutable edition names such as `newsletter-20260928-1.html`; existing editions are never overwritten.
- Editable sources, media weights, candidate rules, score parameters, time zone, layout size, and interests.
- Reduced AI payloads, local source/corroboration adjustment, and token accounting.
- A localhost-only control center bound to `127.0.0.1`.

### Requirements

- Windows 10 or Windows 11.
- Network access to the configured news feeds, Google News, Google Translate GTX, and the selected AI backend.
- In version 2.2.4, the AI backend is still OpenCode CLI, with OpenCode Zen authentication configured.

Python does not need to be preinstalled, and administrator privileges are not required. On first launch, the project downloads a SHA-256-verified portable `uv`, prepares Python 3.12 under `.tools`, and creates a project-local `.venv`.

Install and authenticate OpenCode:

```powershell
npm install -g opencode-ai
opencode auth login --provider opencode
```

Never store API keys in project configuration, documentation, or Git. Let the provider client or a secure credential store manage secrets.

### Quick start

1. Download or clone the repository.
2. Double-click `运行每日新闻.cmd` in the repository root. Do not run it as administrator.
3. On the first launch, wait for portable Python, the virtual environment, and dependencies to be prepared.
4. Your browser opens `http://127.0.0.1:8765/` automatically.
5. Review the environment checks and optionally update and save settings.
6. Click **Generate today's briefing** (`生成今日简报`).

The normal daily workflow is: **double-click `运行每日新闻.cmd` → wait for the browser → click the generate button**.

`每日新闻简报控制中心.html` is the complete UI and can be opened directly for a static preview. A browser cannot start a Python process from a local HTML file, so generation is disabled in preview mode. Keep the launcher window open while using the control center; closing it or running `停止每日新闻控制中心.cmd` stops the local service. History items ask the service to open the corresponding local HTML file safely.

### How a briefing is built

For the first edition of the day, the application:

1. Fetches every enabled source.
2. Keeps the rolling 24 hours ending at the actual run time.
3. Removes non-news items, collection pages, and invalid titles.
4. Groups duplicates and related reports into events.
5. Builds a high-recall rule-based pool of up to 60 events.
6. Sends only stable `event_id`, title, compact summary, and one shared interest list to AI.
7. Requests a scored Top 15 plus 25 additional unranked stories.
8. Applies media weight and independent-source bonuses locally.
9. Translates the final selection with GTX; AI repair is used only when titles fail and for severe Top-10 semantic errors.
10. Publishes 10 headlines plus 30 additional stories with a monotonically increasing daily edition number.

Later same-day runs fetch again but, while code and persistent settings remain compatible, only new events are sent to AI and translation. If there are no new events, no new AI or GTX usage is incurred.

### Local score adjustment

AI produces base importance `I`; the application adjusts the scored Top 15 locally:

```text
P = clamp((W - W0) / (W1 - W0), 0, 1)
F = F0 + deltaF * P
S = min(100, I * F + B)
```

`W` is the highest media weight in the event, `F` is the resulting source factor, `B` is the independent-source bonus, and `S` is the final adjusted score. The control center explains and exposes all parameters.

### Manual commands

```powershell
# Prepare the environment
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

# Start the control center
.\.venv\Scripts\python.exe -m newsletter.webapp --config .\config

# Run once in automatic mode
.\scripts\run_daily.ps1

# Force a full run
.\.venv\Scripts\python.exe -m newsletter run --full --config .\config

# Run tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check newsletter\ui\app.js
```

### Output directories

- `runs/<date>/<run_id>/`: stage artifacts, audit data, and recovery state.
- `archive/<date>/`: immutable HTML, Markdown, and JSON editions.
- `latest/current.json`: pointer to the latest successful publication.
- `logs/`: launcher, control-center, and pipeline logs.
- `config/backups/`: configuration backups created before web-based saves.

### Troubleshooting

- **First-run setup fails:** verify access to the uv/Python release hosts, then launch again.
- **OpenCode check fails:** run `opencode --version` and `opencode auth login --provider opencode`.
- **Some sources fail:** inspect the network, proxy, system clock, and feed URL. A single failed source does not abort other sources.
- **A run lock remains:** make sure no briefing process is active, then run `.\.venv\Scripts\python.exe -m newsletter unlock --config .\config`.
- **Port 8765 is occupied:** run `停止每日新闻控制中心.cmd`, or start the server manually with another `--port`.

For internal design details, see [DESIGN.md](DESIGN.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The proposed 2.3 work is tracked in [ROADMAP_2.3.md](ROADMAP_2.3.md).

### Security principles

- Treat every news article as untrusted data, never as model instructions.
- Validate AI output against stable IDs, schema, counts, and ranges.
- Keep the web service on localhost and validate write-request origins.
- Write configuration and publication pointers atomically.
- Never commit credentials, logs, run artifacts, caches, or temporary model inputs.

## Version and license

Current release: **2.2.4**. A project license has not yet been selected; choosing and adding `LICENSE` is a release requirement for 2.3. Until then, the absence of a license means no additional reuse rights are granted by default.
