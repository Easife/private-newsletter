# Private Newsletter 2.1.0 Economy

这是一个 Windows 优先的自动化每日新闻简报程序。Windows 负责 RSS/Google News 抓取、过滤、聚类、翻译服务访问、渲染、归档和计划任务；OpenCode 通过无界面的 `opencode run` CLI 提供大模型能力，不再需要 WSL，也不要求打开 OpenCode 图形界面。

## 运行结构

完整管线是：

```text
Windows 计划任务
  -> 抓取 -> 过去 24 小时过滤 -> 事件聚类
  -> 规则构造 60 条候选 -> opencode run 一次选出 Top15 + 其余 25 条
  -> 本地来源/多源校正 -> GTX 翻译 -> HTML/Markdown/JSON
  -> 归档 -> 原子更新 latest/current.json
```

每篇新闻和每个事件都使用内容生成的稳定 ID。AI 输入和输出通过 ID 关联，不再依赖数组位置。每次运行写入独立目录及 `manifest.json`；只有完整成功后才发布最新版。

经济模式每天只计划一次新闻选择请求。每条 AI 输入只含 `event_id`、标题和最多 300 字摘要，兴趣清单只发送一次。AI 返回带重要性分数的 Top15，以及另外 25 条无序普通新闻；Top15 的媒体可信度和多来源加分在本地校正。最终版面固定为 10 条头条和 30 条普通新闻。

翻译默认只调用 Google GTX。GTX 成功即直接采用；摘要失败会留空。只有标题翻译失败时才额外调用一次 OpenCode，补译失败标题并同时检查 Top10 是否有严重语义错误。Bing 已从执行路径移除。

## 首次配置

1. 确认 Windows 上已安装 OpenCode CLI，并在 CLI 中完成模型供应商登录或配置。桌面客户端与 CLI 的凭据不一定共享。官方 npm 安装命令是 `npm install -g opencode-ai`；程序也能直接定位 npm 包内的原生程序。
2. 执行 `opencode auth login --provider opencode` 登录 OpenCode Zen。API Key 只交给 OpenCode CLI 管理，不要写入本项目配置或 `.env`。当前配置只列出名称明确带 `-free` 的免费模型。
3. 检查 [pipeline.yaml](config/pipeline.yaml) 中的代理地址。默认使用系统直连；只有本地代理确实运行时才填写两个 `proxy`。
4. 按需修改 [sources.yaml](config/sources.yaml)、[interests.yaml](config/interests.yaml) 和 [terminology.yaml](config/terminology.yaml)。
5. 安装环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

默认翻译不需要 Playwright。

## 手动运行与诊断

准备测试时：

```powershell
.\scripts\run_daily.ps1
.\.venv\Scripts\python.exe -m newsletter doctor --config .\config
```

指定日期（过滤窗口仍以实际启动时刻为终点，日期用于归档）：

```powershell
.\scripts\run_daily.ps1 -RunDate 2026-09-27
```

恢复失败的运行时，必须同时使用原日期和清单中的 `run_id`；如果配置已经改变，系统会拒绝复用旧结果：

```powershell
.\.venv\Scripts\python.exe -m newsletter run --date 2026-09-27 --resume 2026-09-27-063000-1234 --config .\config
```

异常退出可能留下运行锁。确认任务管理器中没有正在运行的简报进程后，才可执行：

```powershell
.\.venv\Scripts\python.exe -m newsletter unlock --config .\config
```

## 安装每日计划任务

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -DailyAt 06:30
```

此任务使用当前用户的交互登录令牌；用户需处于已登录状态。重复触发时会忽略新实例，应用层也有独占锁作为第二道保护。卸载命令：

```powershell
.\scripts\uninstall_task.ps1
```

## 输出

- `runs/<日期>/<run_id>/`：阶段产物、运行清单和可恢复现场。
- `archive/<日期>/`：当天成功发布的 JSON、Markdown、HTML，文件名为 `newsletter-YYYYMMDD-N`，其中 N 是当天从 1 开始的序号。
- `latest/current.json`：最新版提交指针，指向同目录下同名的不可变文件；后续运行只新增更高序号，绝不覆盖旧网页。
- `logs/`：启动器与管线日志。

详细设计见 [架构说明](docs/ARCHITECTURE.md)，首次验证步骤见 [测试计划](docs/TEST_PLAN.md)。
