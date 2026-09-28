# Private Newsletter 2.3 Roadmap / 2.3 路线图

This document records the proposed scope for the next development cycle. It is a plan, not a promise that every item is already implemented.

本文记录下一开发周期的建议范围，方便后续讨论与验收；以下内容尚未在 2.2.4 中实现。

## Release objective / 发布目标

Turn the current Windows/OpenCode-specific application into an extensible, schedulable, distributable briefing platform without weakening its stable-ID, auditability, immutable-publication, and low-token guarantees.

在保留稳定 ID、可审计、不可变发布和低 token 消耗原则的前提下，把当前面向 Windows/OpenCode 的程序升级为可扩展、可定时、可投递并适合其他用户安装的简报平台。

## P0 — Pluggable AI and agent backends / 可插拔 AI 与 Agent 后端

### Goal / 目标

Decouple the editorial pipeline from OpenCode so users can select another model API, a local model, or an agent runner without changing ranking and translation business logic.

解除新闻业务管线对 OpenCode 的直接依赖，使用户可以接入其他模型 API、本地模型或 Agent 执行器。

### Proposed work / 建议工作

- Define a provider-neutral `AIProvider` contract for ranked selection, title repair, health checks, structured output, errors, and usage accounting.
- Move the current `opencode run` implementation into an `OpenCodeCLIProvider` adapter.
- Add at least one OpenAI-compatible HTTP adapter; keep vendor-specific SDKs optional.
- Define an external command/agent adapter with strict JSON input/output and timeouts, without granting article text command privileges.
- Add provider selection, model name, endpoint, timeout, and capability checks to configuration and the UI.
- Normalize input, output, reasoning, and cached token usage where the backend exposes them; clearly label estimates otherwise.
- Store secrets outside versioned YAML: environment variables, OS credential storage, or provider-native authentication.
- Preserve one canonical ranking schema so switching providers does not change downstream event IDs or rendering contracts.

### Acceptance criteria / 验收标准

- The same fixture can complete ranking through OpenCode and at least one non-OpenCode provider.
- No pipeline module imports a concrete provider implementation directly.
- Missing capabilities and invalid credentials are reported before a news run begins.
- Provider changes invalidate incompatible incremental baselines safely.

## P0 — Scheduling and delivery / 定时运行与消息投递

### Goal / 目标

Allow users to configure unattended daily generation and receive the result through email or communication applications.

允许用户配置无人值守的每日运行，并通过邮件或通信应用接收结果。

### Proposed work / 建议工作

- Manage Windows Task Scheduler from the control center, including time zone, run time, enable/disable, next-run preview, and last result.
- Keep a CLI scheduling path for recovery and advanced use.
- Introduce a provider-neutral `DeliveryProvider` contract.
- Implement email delivery first (SMTP or a documented mail API), supporting a summary, archive link, and optional HTML attachment.
- Add webhook-based delivery for communication apps; individual adapters can cover Slack, Discord, Teams, Telegram, Feishu/Lark, or similar services.
- Add retry with bounded exponential backoff, idempotency keys, and a delivery ledger so a rerun does not send the same edition twice unintentionally.
- Separate “briefing generated successfully” from “delivery succeeded”; a delivery failure must not corrupt or roll back the archived briefing.
- Expose delivery tests, last delivery status, and actionable error logs in the UI.

### Acceptance criteria / 验收标准

- A user can create, inspect, pause, resume, and remove a daily schedule without editing scripts.
- A successful scheduled run can deliver through email and at least one webhook channel.
- Credentials never appear in logs, archives, Git, or exported settings.
- Failed deliveries can be retried safely without regenerating the briefing.

## P0 — GitHub engineering baseline and license / GitHub 工程基础与许可证

### Proposed work / 建议工作

- Add GitHub Actions for Python unit tests, JavaScript syntax checks, packaging checks, and linting.
- Run deterministic offline tests on Windows; add another OS for provider-neutral modules where practical.
- Add fixtures/mocks for feeds, AI responses, translation, time, and delivery so CI never consumes model tokens or sends messages.
- Add dependency caching with lock/hash validation and artifact retention for failed tests.
- Add pull-request and release workflows, including version/tag consistency checks.
- Choose and add a `LICENSE`. MIT and Apache-2.0 are common permissive candidates, but the repository owner must make the legal choice before the 2.3 release.
- Add contribution guidance, issue templates, a security-reporting policy, and an explicit secrets policy.

### Acceptance criteria / 验收标准

- Every pull request runs without external credentials, paid APIs, or live news access.
- A release tag cannot pass when package, UI, and changelog versions disagree.
- The selected license is present and referenced by the README and package metadata.

## P1 — Configuration evolution and reliability / 配置演进与可靠性

- Introduce an explicit configuration schema version and automatic, backed-up migrations.
- Validate provider, schedule, and delivery settings before saving.
- Add structured run/delivery diagnostics and a downloadable redacted support bundle.
- Improve crash recovery, stale-lock diagnosis, cancellation, timeout boundaries, and partial-source health reporting.
- Add retention settings for runs, logs, caches, and archived editions without ever deleting by default.
- Add import/export for non-secret user settings.

## P1 — Distribution and onboarding / 分发与新用户体验

- Produce a signed or checksum-verifiable Windows release archive with a single documented entry point.
- Consider an optional native launcher or tray application so the local backend can start at login without keeping a terminal visible.
- Add a first-run setup wizard for provider, interests, sources, schedule, and delivery.
- Keep advanced YAML/CLI access available and document how UI settings map to files.
- Evaluate localization infrastructure so the UI itself can switch between Chinese and English without duplicating templates.

## P1 — Quality and editorial evaluation / 质量与编辑评估

- Build a small versioned evaluation set for deduplication, non-news filtering, candidate recall, Top-10 quality, and translation failures.
- Compare providers on selection overlap, important-event recall, latency, token use, and cost.
- Add source-diversity and concentration reports to each run without turning them into hard ranking rules by default.
- Track why candidates were excluded and make the audit easier to inspect from the control center.

## Decisions required before implementation / 开工前需要确认

1. Which non-OpenCode provider should be the first reference adapter?
2. Should secrets use Windows Credential Manager, environment variables, or both?
3. Which email path and first communication app/webhook should be supported?
4. Should scheduling remain Windows Task Scheduler-based or also support a long-running internal scheduler?
5. Which license should the owner select: MIT, Apache-2.0, or another license?
6. Is macOS/Linux execution part of 2.3, or should only provider-neutral modules be cross-platform-tested?

## Suggested implementation order / 建议实施顺序

1. Configuration schema versioning and secret boundary.
2. `AIProvider` interface, OpenCode adapter extraction, fixtures, and a second adapter.
3. Offline GitHub Actions and release/version checks.
4. `DeliveryProvider`, email, one webhook adapter, and the delivery ledger.
5. Scheduling UI and unattended-run integration.
6. Installer/onboarding, localization, documentation, and final license/release work.
