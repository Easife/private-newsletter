# Changelog

## Unreleased

## v0.2.0
发布日期: 2026-08-28

### 新增
- 翻译三层 fallback: Google GTX API → Google Web (Playwright) → LLM
- Bing 翻译默认禁用, 保留代码作为备用 (--enable-bing)
- 多语言 batch 翻译: 按 language 分组 + batch 拆分, 不混合语言提交
- 模型 fallback 机制: 评分与翻译最多 5 个模型按序 fallback (优先 OpenCode 免费模型)
- 缓存语义: resume 完整复用 / force-refresh 全量 / retranslate-only 独立, 删除"成功率<90%自动重翻"
- `--retranslate-only` 预留参数

### 修复
- 新闻图片错配: renderer 不再跨新闻复用/re匹配图片, 只原样使用每条新闻自带 RSS image_url, 无图一律占位
- RSS 图片覆盖率低(约22%)时不再因关键词/group 匹配导致错图

### 变化
- 头条布局: 左图右文, 单条约两倍普通卡片宽 (面积约4倍), 保持突出但非超大 Hero 卡
- 头条图片: 固定高度容器 + object-fit:cover 裁剪, 图片不撑高卡片
- 来源标签配色系统: 免费=浅绿/绿字, 付费=浅红/红字, Google 搜索跳转=浅蓝/蓝字
- 桌面端 max-width: 720px → 1200px, 普通新闻保持两列, 移动端基本适配
- 新增项目规范冻结依据 PROJECT_RULES.md

### 测试
- Google Web provider 独立测试 test_google_web_translate.py: 60/60 成功
- 完整 pipeline 真实测试通过 (翻译质量 100%, 图片 0 错配 0 复用)

## v0.1.0
发布日期：2026-08-27

### 新增
- RSS 新闻抓取流程
- RSS 代理配置支持
- LLM 三阶段新闻处理流程
- HTML 新闻简报生成
- 新闻图片获取与展示支持
- UI 原型设计目录
- Git 版本管理

### 修复
- 修复 RSS 抓取因代理未配置导致全部失败的问题
- 修复 Windows 控制台 UTF-8 中文日志乱码问题

### 文档
- 新增 RSS 抓取环境配置文档
- 新增编码规范文档
