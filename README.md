# Amazon Selling Monitor

中文 Streamlit Dashboard，用于实时查看 ASIN `B0GXYYZPBW` 的销售、SP 广告、全量广告和经营上下文。

## 本地运行

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

如果没有配置 Lingxing MCP URL，页面会使用 `data/fixtures/sample_dashboard_payload.json` 的样例数据，并在顶部显示数据源状态。

## Streamlit Cloud Secrets

在 Streamlit Cloud 的 app secrets 中配置：

```toml
ASIN = "B0GXYYZPBW"
LINGXING_MCP_URL = "http://34.143.132.97:8368/lingxing_config_B0GXYYZPBW/"
LINGXING_MCP_TRANSPORT = "streamable_http"
PANGOLINFO_API_TOKEN = "paste-token-in-streamlit-secrets-only"
```

`LINGXING_MCP_URL` 必须是 Streamlit Cloud 可以直接访问并完成 MCP 会话的端点。当前 Lingxing FastMCP 服务使用 Streamable HTTP，建议把 `LINGXING_MCP_TRANSPORT` 显式设为 `streamable_http`；不配置时应用会先尝试 Streamable HTTP，再回退到 SSE。Codex 本地配置里的 MCP config URL 不一定等同于公开可用的 MCP endpoint；如果该地址返回 404 或 MCP 握手失败，页面会显示“实时数据源不可用”，不会继续展示样例业务数字。

`PANGOLINFO_API_TOKEN` 只用于 Pangolin public context：Listing 前台 offer、delivery promise、核心关键词 SERP、竞品选择与排名上下文。不要把真实 token 写入 Git；只放在 Streamlit Cloud Secrets。更新 secrets 或拉取新 commit 后，从 Streamlit Cloud 的 Manage app 重启应用，并点击页面里的 `Refresh Data` 清理缓存。

实时 MCP 模式需要 Python 3.10+ 才会安装 `mcp>=1.9`。本仓库的 `runtime.txt` 已配置 `python-3.11.9`；如果本地旧 `.venv` 是 Python 3.8，只能跑普通单元测试，不能跑 live MCP 拉数。

## 当前目标

- SP ACOS 目标：49.93%
- SP 日预算：前期 300 美元，后续 600 美元
- SP 广告订单目标：22-60 pc/day

## 数据口径

- `SP 广告`：只纳入明确或可推断为 Sponsored Products 的 campaign，用于 SP 目标追踪。
- `全量广告`：纳入 SP、SB、SD、SBV 和 unknown，用于整体广告经营监控。
- Auto / Manual 是 SP 内部投放类型，不作为排除 SP 的依据。
