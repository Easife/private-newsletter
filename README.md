# 私人新闻简报

每天获取重要新闻，结合个人兴趣生成简洁的每日新闻简报。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 确保 opencode 已安装且可用
opencode --version

# 3. 编辑配置（可选）
# 修改 config/sources.yaml 添加或删除新闻源
# 修改 config/interests.yaml 调整兴趣

# 4. 运行
python run.py
```

## 配置

- `config/sources.yaml` - 新闻来源（RSS URL、权重、语言）
- `config/interests.yaml` - 用户兴趣（长期 + 近期关注）
- `config/newsletter.yaml` - 简报格式（分区、条数、语言偏好）

## 输出

生成的简报保存在 `output/` 目录，格式为 Markdown。

## 命令行参数

```
python run.py --date 2026-08-18    # 指定日期
python run.py --config ./my-config  # 自定义配置目录
python run.py --model provider/model  # 指定 LLM 模型
python run.py -v                    # 详细日志
```
