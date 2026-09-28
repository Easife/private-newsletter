# Private Newsletter 2.2.0

Windows 本机运行的自动化每日新闻简报：抓取多语言新闻源，在过去24小时滚动窗口内过滤和聚类，以规则压缩候选池，通过 OpenCode 免费模型选择重要新闻，使用 Google GTX 翻译，最终生成10条头条与30条普通新闻的 HTML、Markdown 和 JSON 版本。

程序不依赖 WSL，也不要求打开 OpenCode 桌面客户端。日常操作通过名为 **Private Newsletter 控制中心** 的本机网页完成，入口是根目录的 `运行每日新闻.cmd`。

## 主要功能

- 一次点击完成抓取、过滤、事件合并、AI 选择、翻译、渲染和版本归档。
- 本机控制台显示环境检查、运行模式、即时日志、错误与成功结果。
- 同日首次运行处理过去24小时；同日后续运行只评估上次抓取后出现的全新事件。
- 每次成功输出独立文件，例如 `newsletter-20260928-1.html`、`newsletter-20260928-2.html`，从不覆盖旧版。
- 最近20份简报可直接从控制台打开。
- 页面内编辑来源、权重、候选规则、评分系数、输出数量、时区和兴趣参考。
- 设置保存前校验并自动备份；关键设置变化会自动回退为完整运行。
- OpenCode 请求和 GTX 翻译均按需执行，并记录模型 token。

## 系统要求

- Windows 10 或 Windows 11。
- Python 3.11 或更新版本。
- 能访问配置中 RSS、Google News、Google Translate GTX 和 OpenCode 的网络环境。
- 已安装 OpenCode CLI，并完成 OpenCode Zen 登录。

安装 OpenCode CLI：

```powershell
npm install -g opencode-ai
opencode auth login --provider opencode
```

API Key 只应交给 OpenCode 自己的凭据系统管理。不要写入项目配置、`.env`、文档或 Git 仓库。

## 最快开始

1. 下载或克隆仓库。
2. 双击根目录的 `运行每日新闻.cmd`。
3. 首次启动会自动创建 `.venv` 并安装依赖。
4. 浏览器打开 `http://127.0.0.1:8765/` 后，确认 Python、虚拟环境、配置和 OpenCode 检查结果。
5. 默认设置可直接使用；按需调整后点击“保存全部设置”。
6. 点击“生成今日简报”。

完成以上一次性准备后，日常使用只需双击 `运行每日新闻.cmd`，再点击“生成今日简报”。无需打开终端、WSL 或 OpenCode 桌面客户端。

控制台只绑定 `127.0.0.1`，不会开放给局域网或互联网。关闭启动窗口会停止控制台服务，但不会删除已经完成的简报。

## 首次手动安装

如果不希望启动器自动安装，可以在 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe -m newsletter doctor --config .\config
```

随后启动控制台：

```powershell
.\.venv\Scripts\python.exe -m newsletter.webapp --config .\config
```

## 每日生成逻辑

### 当天第一次生成

1. 从所有来源抓取新闻。
2. 以点击时刻为终点保留过去24小时。
3. 过滤非新闻、无效标题和配置不允许的条目。
4. 合并相同事件与相关报道。
5. 用本地规则构造最多60条高召回候选。
6. 向 AI 发送 `event_id`、标题、精简摘要和一次兴趣清单。
7. AI 返回带重要性分数的 Top15，以及另外25条无序新闻。
8. 本地应用来源权重和多来源加分，得到最终 Top15。
9. GTX 翻译最终选择；只有标题失败时才调用一次 OpenCode 补译并检查 Top10 严重语义错误。
10. 渲染10条头条和30条普通新闻，分配当天递增版本号。

### 同一天再次生成

代码和持久设置未变化时，程序自动进入增量模式：

- 重新抓取和规则过滤，不盲目复用旧 RSS 结果。
- 用稳定新闻 ID 与上次原始抓取比较。
- 与旧条目聚为同一事件的新报道不重复进入 AI；只有全部条目均为新的事件才视为全新事件。
- 只对全新事件调用 AI，并只翻译最终进入合并结果的新事件。
- 新的有分数事件与上一版 Top15 合并重排；普通新闻由被挤出的 Top15、新增普通新闻和旧普通新闻依次补足。
- 最终仍输出10+30；如果没有新事件，不产生 AI 或 GTX 消耗。

如果来源、权重、公式、数量、长期兴趣或代码发生变化，系统会执行完整运行，避免新旧规则混用。一次性兴趣不破坏同日增量基线。

## 兴趣参考

- **长期兴趣**：持续保存在 `config/interests.yaml`，每次 AI 选择都会参考。适合长期领域，如国际政治、AI、芯片、能源和基础设施。
- **一次性兴趣**：只影响下一次成功生成，随后自动清空。适合当天临时关注的会议、人物、地区或突发事件。失败运行不会清空，确保意图不会因错误丢失。

兴趣只作为公共重要性之后的次要参考。程序不生成独立兴趣分，也不会用兴趣替代媒体可信度或多来源校正。

## 来源权重公式

AI 给出基础重要性 `I`，程序在本地对 Top15 应用：

```text
P = clamp((W - W₀) / (W₁ - W₀), 0, 1)
F = F₀ + ΔF × P
S = min(100, I × F + B)
```

- `W`：事件中最高媒体权重。
- `W₀` / `W₁`：权重映射起点与终点。
- `P`：媒体权重在区间内的相对位置。
- `F₀`：最低来源乘数。
- `ΔF`：从最低权重到最高权重增加的乘数范围。
- `B`：独立来源加分；默认1/2/3/4+来源分别为0/2/4/6。
- `S`：用于 Top15 重排的最终校正分，最高100。

默认 `W₀=0.65`、`W₁=0.90`、`F₀=0.90`、`ΔF=0.10`。例如 `W=0.85` 时，`P=0.80`、`F=0.98`。

## 添加或修改新闻来源

在控制台“新闻来源”页面可以新增、删除和修改来源。每个来源包含：

- 稳定、唯一的小写 `source_id`。
- 显示名称。
- RSS URL，或者 Google News 站内搜索式。
- 0–1 的媒体权重。
- 原始语言。
- 免费或付费访问属性。
- 用于维护和候选规则的标签。
- Google News 来源可另外设置 `HL`、`GL` 和 `CEID` 地区参数。

保存后会生成时间戳备份至 `config/backups/`。如果新来源无法访问，只会在运行状态中记录该来源失败；其他来源仍会继续抓取。

## 命令行与计划任务

手动运行自动模式：

```powershell
.\scripts\run_daily.ps1
```

强制完整运行：

```powershell
.\.venv\Scripts\python.exe -m newsletter run --full --config .\config
```

安装每日计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -DailyAt 06:30
```

当前计划任务使用当前用户的交互登录令牌，用户需保持登录状态。重复触发会被计划任务和应用锁共同阻止。

## 输出目录

- `runs/<日期>/<run_id>/`：每个阶段的机器可读产物、日志依据和恢复现场。
- `archive/<日期>/`：不可变 HTML、Markdown、JSON 简报。
- `latest/current.json`：最近一次成功发布的指针。
- `logs/`：启动器、控制台和管线日志。
- `config/backups/`：网页设置保存前的配置备份。

这些运行目录默认被 `.gitignore` 排除。

## 故障排查

- **虚拟环境失败**：确认 Python 3.11+ 已安装并可由 `py` 或 `python` 命令找到。
- **OpenCode 显示异常**：运行 `opencode --version` 和 `opencode auth login --provider opencode`。
- **无法抓取全部来源**：检查网络、代理、系统时间和来源 URL；单一来源失败不会终止其他来源。
- **提示已有运行锁**：先确认任务管理器中没有简报进程，再执行 `.\.venv\Scripts\python.exe -m newsletter unlock --config .\config`。
- **设置保存失败**：页面会显示具体字段错误；旧配置不会被覆盖。
- **端口8765被占用**：关闭旧控制台窗口，或使用 `python -m newsletter.webapp --port 其他端口`。

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

项目设计、模块职责、增量合并和扩展说明见 [DESIGN.md](DESIGN.md)。架构摘要见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 安全原则

- 新闻文本一律视为不可信数据，不允许成为模型指令。
- AI 响应通过 JSON Schema、稳定 ID 和完整性检查。
- 控制台只监听 localhost，并验证写请求来源。
- 配置写入使用临时文件和原子替换。
- API Key、运行产物、日志、缓存和临时模型输入不得提交 Git。
