# Amazon Selling Monitor

中文 Streamlit Dashboard，用于实时查看父 ASIN 下所有子 ASIN 的销售、SP 广告、全量广告和经营上下文。真实 ASIN、Lingxing endpoint、dashboard URL 和账号信息都只放在 Streamlit/GitHub Secrets 中，仓库里只保留样例占位值。

## 本地运行

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

如果没有配置 Lingxing REST API 或 MCP URL，页面会使用 `data/fixtures/sample_dashboard_payload.json` 的样例数据，并在顶部显示数据源状态。

## Streamlit Cloud Secrets

在 Streamlit Cloud 的 app secrets 中配置：

```toml
ASIN = "your-child-asin"
LINGXING_PARENT_ASIN = "your-parent-asin"
LINGXING_API_BASE_URL = "https://your-lingxing-api.example"
LINGXING_ACCOUNT = "your-lingxing-account"
LINGXING_PROFILE_ID = "your-profile-id"
LINGXING_USER_TOKEN = "paste-x-user-token-in-streamlit-secrets-only"
MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY = "same-secret-as-github-actions"
```

可选配置：

```toml
LINGXING_MCP_URL = "https://your-lingxing-mcp.example/lingxing_config/"
LINGXING_MCP_TRANSPORT = "streamable_http"
MARKET_CONTEXT_SNAPSHOT_URL = "https://raw.githubusercontent.com/<owner>/<repo>/market-context-data/latest.enc.json"
```

数据源优先级是 Lingxing REST API -> Lingxing MCP -> fixture。REST API 会向每个请求统一发送 `X-USER-TOKEN`、`X-LINGXING-ACCOUNT` 和 `X-Profile-Id`，并用 `/api/lingxing/asin-all-list` 自动发现父 ASIN 下的子 ASIN，再用 `/api/lingxing/asin-all` 拉取子体销售、订单、销量、广告和库存。`/api/lingxing/asin-sales` 只作为单个子 ASIN 的轻量销量 fallback；`/api/lingxing/orders` 不作为主数据源，因为父 ASIN 口径可能返回 no store orders data。

`LINGXING_MCP_URL` 是备用项，必须是 Streamlit Cloud 可以直接访问并完成 MCP 会话的端点。当前 Lingxing FastMCP 服务使用 Streamable HTTP，建议把 `LINGXING_MCP_TRANSPORT` 显式设为 `streamable_http`；不配置时应用会先尝试 Streamable HTTP，再回退到 SSE。Codex 本地配置里的 MCP config URL 不一定等同于公开可用的 MCP endpoint；如果 REST 和 MCP 都失败，页面会显示“实时数据源不可用”。如果当前刷新失败但本 session 已经有过成功数据，页面会保留上一份成功快照并标记 stale。

`MARKET_CONTEXT_SNAPSHOT_URL` 指向 GitHub Actions 发布到独立 `market-context-data` 分支的加密完整 Market Context 快照。配置后，Streamlit 页面会优先读取 `latest.enc.json` 并用 `MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY` 解密，不在用户访问时实时跑 Pangolin 全量抓取。这个 key 必须和 GitHub Actions 中的同名 secret 完全一致。

GitHub Actions 目标每 10 分钟生成一次完整 Market Context 快照。定时触发使用错峰 cron，避开 GitHub Actions 每小时开始附近的高峰；但 GitHub 官方不保证 `schedule` 精确准时，负载高时可能延迟或丢弃。页面默认 20 分钟后才把 snapshot 标记为 stale，并继续展示最近一份完整快照。请在 GitHub 仓库 Secrets 中配置：

```text
PANGOLINFO_API_TOKEN
MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY
MARKET_CONTEXT_ASIN
MARKET_CONTEXT_MARKETPLACE
MARKET_CONTEXT_LEAF_CATEGORY_LABEL
MARKET_CONTEXT_LEAF_CATEGORY_NODE_ID
MARKET_CONTEXT_BEST_SELLERS_URL
MARKET_CONTEXT_NEW_RELEASES_URL
MARKET_CONTEXT_CORE_KEYWORDS
```

可选 GitHub Secrets：

```text
MARKET_CONTEXT_PRODUCT_URL
MARKET_CONTEXT_PINNED_COMPETITOR_ASINS
MARKET_CONTEXT_EXCLUDED_COMPETITOR_ASINS
```

`MARKET_CONTEXT_PRODUCT_URL` 只有在默认 `https://www.amazon.com/dp/<ASIN>` 被跳转或拦截时才需要配置，用于补齐 public listing 字段。

Action 生成的是加密后的 `latest.enc.json`，并强制推送到 `market-context-data` 分支。仓库默认分支不保存真实 ASIN、真实 endpoint、dashboard URL 或明文 Market Context 数据。请确认 GitHub repository 的 Actions 权限允许 `Read and write permissions`，否则 workflow 无法更新 data branch。

如果需要比 GitHub schedule 更稳定的兜底，可以在腾讯云服务器用 cron 调 GitHub `repository_dispatch`，触发同一个 workflow：

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_DISPATCH_TOKEN" \
  https://api.github.com/repos/Elio-Koh/amazon-selling-monitor/dispatches \
  -d '{"event_type":"market_context_snapshot"}'
```

`GITHUB_DISPATCH_TOKEN` 需要具备触发 Actions/workflow dispatch 的权限，只保存在腾讯云环境变量或服务器 secret 中，不写入 repo。

`PANGOLINFO_API_TOKEN` 用于 GitHub Actions 生成 public context：Listing 前台 offer、delivery promise、核心关键词 SERP、竞品选择与排名上下文。不要把真实 token 或真实目标配置写入 Git；只放在 Streamlit Cloud Secrets 或 GitHub Secrets。更新 secrets 或拉取新 commit 后，从 Streamlit Cloud 的 Manage app 重启应用，并点击页面里的 `Refresh Data` 清理缓存。

实时 MCP 模式需要 Python 3.10+ 才会安装 `mcp>=1.9`。本仓库的 `runtime.txt` 已配置 `python-3.11.9`；如果本地旧 `.venv` 是 Python 3.8，只能跑普通单元测试，不能跑 live MCP 拉数。

## 当前目标

- SP ACOS 目标：49.93%
- SP 日预算：前期 300 美元，后续 600 美元
- SP 广告订单目标：22-60 pc/day

## 数据口径

- `SP 广告`：只纳入明确或可推断为 Sponsored Products 的 campaign，用于 SP 目标追踪。
- `全量广告`：纳入 SP、SB、SD、SBV 和 unknown，用于整体广告经营监控。
- Auto / Manual 是 SP 内部投放类型，不作为排除 SP 的依据。
