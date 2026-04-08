# Locust 压测：QA WebUI `/api/qa/stream`

依赖已写入 `pyproject.toml` 的 `dev` 组（`locust>=2.32,<3`）。安装：

```bash
uv sync
```

## 前置

1. 启动 QA WebUI（需 `embedding` + `llm` 等，见主 README），例如：

   ```bash
   uv sync --extra embedding --extra llm
   uv run uvicorn qa.webui.app:app --host 127.0.0.1 --port 8766
   ```

2. 探活：`curl -sSf http://127.0.0.1:8766/api/health`

## 运行

```bash
uv run locust -f scripts/load/locust/locustfile.py --host http://127.0.0.1:8766
```

浏览器打开 <http://localhost:8089>，设置并发用户数与 spawn 速率。

若需**阶梯升压**，设置 `LOCUST_USE_SHAPE=1`（会注册 `StagesShape`；此时由 `tick` 调度用户数，Web UI 里填的用户数会被忽略）：

```bash
LOCUST_USE_SHAPE=1 uv run locust -f scripts/load/locust/locustfile.py --host http://127.0.0.1:8766
```

- 默认三阶段：60s@2 用户 → 120s@5 用户 → 180s@10 用户（spawn 速率见 `locustfile.py`）。
- 自定义阶段：`LOCUST_SHAPE_STAGES=30:1:1,60:3:1,120:8:2`

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LOCUST_QA_QUERY` | 短中文问句 | 每次请求的 `query` |
| `LOCUST_QA_K` | `5` | 检索条数；`0` 表示不传 `k`（用服务端默认） |
| `LOCUST_QA_MAX_TOKENS` | `128` | 压测宜**压低**，控制费用与单次时长 |
| `LOCUST_CONNECT_TIMEOUT_S` | `10` | 连接超时（秒） |
| `LOCUST_READ_TIMEOUT_S` | `600` | 读 SSE 总超时（秒） |
| `LOCUST_USE_SHAPE` | 未设置 | 设为 `1` 时启用阶梯升压 `StagesShape` |
| `LOCUST_SHAPE_STAGES` | 见 `locustfile.py` | 阶梯形状，格式见上文 |

示例：

```bash
LOCUST_QA_MAX_TOKENS=64 LOCUST_QA_QUERY="你好" \
  uv run locust -f scripts/load/locust/locustfile.py --host http://127.0.0.1:8766
```

## 风险与费用

- 每次请求会走真实 **embed → ES → LLM**；并发越高，**API 费用与配额**消耗越快。
- 勿对生产环境或未授权集群做高压测。
- 指标解释：Locust 报表中的响应时间为**读完整个 SSE 流**的耗时，与 `monitor.log` 中 `total_ms` 可对齐观察。

## 参考

- 计划文档：[doc/plan/v1.1.2-locust-load-test-plan.md](../../doc/plan/v1.1.2-locust-load-test-plan.md)
