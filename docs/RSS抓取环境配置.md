# RSS 抓取环境配置

> 本文档记录 RSS 抓取的网络环境要求和代理配置方法。
> 遇到 RSS 抓取失败时，请先查阅本文档。

---

## 1. 为什么需要代理

本项目运行在无法直接访问外网的环境中：

- **WSL**：网络命名空间隔离，无法直接访问互联网
- **Windows**：需要通过 Clash 代理访问境外 RSS 源（NYT、BBC、Guardian 等）

因此 RSS 抓取必须配置代理。

---

## 2. 代理配置

### 2.1 代理地址

```
http://127.0.0.1:7897
```

### 2.2 配置位置

`config/newsletter.yaml` 中的 `fetch.proxy` 字段：

```yaml
fetch:
  timeout: 15
  max_concurrent: 5
  ssl_verify: false
  proxy: "http://127.0.0.1:7897"
```

### 2.3 常见错误

**错误：proxy 被注释掉**

```yaml
fetch:
  # proxy: "http://127.0.0.1:7897"   ← 不生效！
```

**正确：proxy 未注释**

```yaml
fetch:
  proxy: "http://127.0.0.1:7897"     ← 生效
```

### 2.4 环境变量备选

如果 `newsletter.yaml` 中未配置 proxy，程序会依次检查：

1. `fetch_config.get("proxy")`
2. `os.environ.get("HTTPS_PROXY")`
3. `os.environ.get("HTTP_PROXY")`

三者都为空时，`proxies=None`，请求直连外网（会失败）。

---

## 3. Python requests 代理调用链路

```
run.py
  → src/main.py run()
    → proxy_url = fetch_config.get("proxy") or env HTTPS_PROXY or env HTTP_PROXY
    → proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    → fetch_all(..., proxies=proxies)
      → fetch_from_source(..., proxies=proxies)
        → requests.get(..., proxies=proxies)
```

关键点：`proxies=None` 时 requests 不走代理，直连目标服务器。

---

## 4. 如何判断是代理问题还是 RSS 源问题

### 快速判断

```bash
# 1. 测试代理是否可用
curl.exe -x http://127.0.0.1:7897 https://httpbin.org/ip
# 应返回非国内 IP（如 64.118.x.x）

# 2. 测试直连是否可用
curl.exe https://httpbin.org/ip
# 如果返回国内 IP，说明直连被墙，必须走代理

# 3. 测试 RSS 源
curl.exe -x http://127.0.0.1:7897 https://feeds.bbci.co.uk/news/rss.xml
# 应返回 XML 内容
```

### 判断逻辑

| 现象 | 判断 |
|------|------|
| 所有 RSS 源都超时/连接失败 | 代理问题 |
| 部分源成功，部分失败 | 源站问题（403/404/超时） |
| 代理返回 503 | Clash 代理服务异常，需重启 |
| 代理返回 200 但 RSS 解析失败 | RSS 格式问题 |

---

## 5. 常用测试命令

```bash
# 测试代理连通性
curl.exe -x http://127.0.0.1:7897 https://httpbin.org/ip

# 测试 RSS 源（替换 URL）
curl.exe -x http://127.0.0.1:7897 https://feeds.bbci.co.uk/news/rss.xml

# Python 测试
python -c "import requests; r=requests.get('https://httpbin.org/ip',proxies={'https':'http://127.0.0.1:7897'},verify=False); print(r.json())"
```

---

## 6. 故障案例

### 案例：代理未启用导致 RSS 0 条（2026-08-22）

**现象**：运行 `python run.py --raw-file data/raw_news.json`，所有 17 个 RSS 源全部超时，返回 0 条新闻。

**排查过程**：
1. 测试代理连接 → 代理端口 7897 开放，但返回 503
2. 检查 newsletter.yaml → `proxy` 被注释掉
3. 检查环境变量 → 未设置 HTTP_PROXY/HTTPS_PROXY
4. 最终 `proxies=None`，请求直连外网被墙

**修复**：取消 `newsletter.yaml` 中 proxy 的注释。

**修复后结果**：
- 343 条新闻成功抓取
- 9/17 来源成功
- 343/343 新闻包含完整 URL
- 74 条新闻包含图片 URL

**失败源（非代理问题）**：

| 来源 | 失败原因 |
|------|---------|
| Reuters | 连接被中断 |
| AP | rsshub.app 返回 403 |
| Economist | 返回 403 |
| 新华社 | RSS URL 返回 404 |
| 日经 | RSS URL 返回 404 |
| 联合早报 | RSS 解析失败 |
| BBC World/BBC | 超时 (15s) |

---

*创建时间：2026-08-22*
