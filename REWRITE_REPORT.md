# 每日新闻简报 0.1.0 历史重写报告

> 本文记录第一次 Windows 单环境重写，已被 2.1.0 经济版方案取代。当前实现、测试结果与 token 数据请以 `README.md`、`docs/ARCHITECTURE.md` 和 `RUN_REPORT_2026-09-28_ECONOMY.md` 为准。

## 结论

程序已按“单一 Windows 运行环境 + OpenCode 无界面 CLI + Python 总调度器”的方向完成重写。新版本不再依赖 WSL，也不需要在每日任务运行时打开 OpenCode 客户端界面。Windows 计划任务直接启动 Python 总管线，AI 阶段按需执行 `opencode run`。

本次只完成了代码与文档交付，严格按要求没有安装依赖、启动服务、联网抓取、导入程序、执行静态检查或运行测试。

## 保留和吸收的原方案

- 保留原来的新闻源结构、来源权重、语言、标签和付费媒体属性，并为每个来源补充稳定 `source_id`。
- 保留 RSS 与 Google News RSS 两种固定抓取方式，避免把来源名称和抓取渠道混为一谈。
- 历史版本曾保留多级翻译 provider；2.1.0 已改为 GTX 主路径与条件式 OpenCode 标题补救。
- 保留头条、普通新闻、备选新闻的三段选择概念，以及 JSON、Markdown、HTML 三种产物。
- 保留用户长期/近期兴趣和术语表，并真正接入 AI 评分与翻译过程。

## 重新设计的部分

### 1. 取消 WSL 业务管线

旧方案把网络工作放在 Windows、AI 工作放在 WSL，导致路径、超时、日志、进程生命周期和恢复状态都跨环境耦合。新版本中所有 Python 业务代码都运行在 Windows；OpenCode 仅作为本机 AI 后端，通过 `opencode run --pure --format json` 按需调用。

### 2. 新增唯一总调度器

`newsletter.pipeline.run_pipeline()` 是唯一业务总入口，依次执行：

```text
fetch -> filter -> deduplicate -> rank -> translate -> render -> publish
```

PowerShell 不再拼接各业务阶段，只负责环境和进程入口。命令行、手动运行与计划任务都调用同一个总调度器，避免出现三套行为。

### 3. 消除索引关联

所有原始新闻使用内容推导的 `item_id`，事件组使用成员集合推导的 `event_id`。AI 评分必须返回本批次完整且不重复的 `event_id`；AI 翻译必须返回完整且不重复的 `item_id`。本地还会再次验证合法 ID、分数范围、重复项和遗漏项。

因此原来的 0/1 基 `item_index` 错位、排名缓存按数组位置套用、并发顺序改变后数据串位等问题在数据模型层被移除。

### 4. 可验证恢复，不再把“文件存在”当缓存

每次运行使用独立 `run_id` 和 `manifest.json`，其中记录：

- 程序版本、Python 源码指纹、目标日期、配置哈希；
- 各阶段运行/完成/失败状态；
- 每个阶段的正式产物和数量元数据；
- 最终成功或错误信息。

`--resume` 只接受相同源码指纹、同日期、同配置哈希的运行，并检查对应阶段产物。即使忘记手动提升版本号，Python 代码改变也会被识别；任何来源、兴趣、术语和管线配置变化同样会拒绝复用旧结果。

### 5. 严格日期语义

发布时间统一转换成 UTC 保存，再用 `Asia/Shanghai` 判断目标日期。默认不收录缺少发布时间的项目；指定日期没有新闻时直接失败，不会退回全量历史新闻。未显式给出日期时，总调度器也按配置时区计算，而不是依赖进程所在系统的偶然时区。

### 6. 确定性和安全发布

- 抓取虽然并发，但结束后按稳定字段排序，因此完成顺序不会改变后续 AI 输入。
- 聚类使用代表项贪心匹配，避免 Union-Find 因传递关系把多个弱相关事件串成巨型组。
- leader 只出现一次，`group_members` 明确排除 leader。
- HTML 对文字和属性转义，只允许 HTTP/HTTPS 链接，图片仅取事件 leader 的图片。
- 输出先写运行目录，再写日期归档和带 `run_id` 的不可变 latest 文件，最后原子写入 `latest/current.json` 作为提交点。失败运行不会成为最新版。

### 7. OpenCode 调用方式

AI 客户端检查 CLI 版本、创建临时请求附件、执行免费模型、读取 JSON 事件流并删除 session。新闻文本始终标注为不可信数据，不允许作为指令执行；CLI 不启用自动工具权限，使 OpenCode 在这里仅承担模型推理职责。

模型收到 JSON Schema 并被要求只输出 JSON，业务层继续执行 ID 和字段完整性验证。排名和翻译各配置最多五个明确带 `-free` 标识的 `provider/model` 回退项。

实现依据为 OpenCode 官方的 [Server 文档](https://dev.opencode.ai/docs/server/) 和 [SDK 文档](https://opencode.ai/docs/sdk/)。

## 原审查问题的处理对应

| 原问题 | 新版本处理 |
|---|---|
| 翻译 0/1 基索引错位 | 全面改用 `item_id` |
| leader 重复进入成员 | 渲染时显式排除 leader |
| Resume 只检查文件存在 | 清单状态 + 日期 + 配置哈希 + 产物 |
| 排名按位置对应 group | AI 和缓存统一使用 `event_id` |
| Windows/WSL 没有总调度器 | Windows 单一 Python 总调度器 |
| interests 未进入评分 | 规则预选和 AI 提示均使用真实兴趣 |
| 配置五个模型但只用两个 | 最多五个逐项回退，空列表使用默认模型 |
| Bing 配置与分支行为不一致 | 2.1.0 已从执行路径完全移除 Bing |
| 固定总超时、日志不实时 | HTTP 请求逐批超时；每次运行独立日志 |
| RSS 并发顺序不稳定 | 完成后确定性排序 |
| 时区处理不完整 | UTC 存储、配置时区筛选 |
| 无新闻时退回全部日期 | 空结果明确失败 |
| Playwright 未声明 | 作为 `google-web` 可选依赖声明 |
| 假配置和双重来源策略 | 只保留代码实际读取的配置项和单一来源策略 |
| 文档互相矛盾 | README、架构、测试计划以当前实现为准 |

## 交付结构

```text
private-newsletter-rewrite/
├─ newsletter/               Python 业务包与总调度器
├─ config/                   管线、来源、兴趣、术语
├─ scripts/                  安装、服务、每日运行、计划任务
├─ docs/ARCHITECTURE.md      架构与状态保证
├─ docs/TEST_PLAN.md         尚未执行的分阶段测试计划
├─ README.md                 使用与运维说明
├─ pyproject.toml            项目和依赖声明
└─ REWRITE_REPORT.md         本报告
```

## 首次测试前需要确认

1. Windows 的 `opencode` 命令已加入 PATH，并已配置可用的默认模型。
2. `config/pipeline.yaml` 当前沿用了原项目的 `127.0.0.1:7897` 代理；若本机代理不同必须先修改。
3. 运行计划任务的当前 Windows 用户必须已通过 `opencode auth login` 配置模型凭据；桌面端登录不一定与 CLI 共享。
4. 计划任务默认只在当前用户已登录时运行，这是为了避免模型凭据、代理和用户环境变量在非交互账户下丢失。

## 当前验证状态

已于 2026-09-27 使用 OpenCode Zen 免费模型完成端到端运行：15 个来源全部成功，871 条原始新闻经过日期过滤后形成 39 个事件，排名、翻译、JSON/Markdown/HTML 渲染与原子发布全部完成。详见 `TEST_RUN_REPORT_2026-09-27_CLI_SUCCESS.md`。计划任务的实际定时触发仍需单独演练。
