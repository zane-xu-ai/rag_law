# rag_law

法律类 RAG（MVP）：文档切分、向量检索、LLM 问答。详见 [`doc/plan/v1.0.0-rag-law-mvp-plan.md`](doc/plan/v1.0.0-rag-law-mvp-plan.md)。

## 环境配置与启动

### 前置条件

- Python **3.11+**
- 推荐使用 [**uv**](https://docs.astral.sh/uv/) 管理依赖与虚拟环境（安装：`curl -LsSf https://astral.sh/uv/install.sh | sh`，或见官方文档）。

### 安装依赖（uv）

在项目根目录执行：

```bash
cp .env.example .env   # 复制后按注释填写，详见下文「环境变量」
uv sync
```

`pyproject.toml` 中配置了 `[tool.uv] default-groups = ["dev", "web"]`，因此 **`uv sync` 会默认安装 `dev`（pytest、Elasticsearch 客户端等）与 `web`（FastAPI、uvicorn 等）**，与 CI 中 `pip install -e ".[dev,web]"` 等价，一般**不必**再写 `--group dev` / `--group web`。

按需叠加**可选依赖**（可组合多条 `--extra`）：

| 场景 | 命令 |
|------|------|
| 仅核心 + 开发 + Web（默认） | `uv sync` |
| 本地向量编码（BGE-M3）、入库脚本 | `uv sync --extra embedding` |
| OpenAI 兼容 LLM、问答脚本 | `uv sync --extra llm` |
| 完整 RAG（入库 + 问答 CLI/Web） | `uv sync --extra embedding --extra llm` |
| 仅 ES 客户端（与默认 dev 重叠时可不装） | `uv sync --extra es` |
| 阿里云 OSS 相关 | `uv sync --extra oss` |

同步后使用项目内解释器，建议统一用 **`uv run …`**，或先 `source .venv/bin/activate` 再运行命令。

### 启动与访问

**Elasticsearch（多数流程需要）**：本地可起示例集群：

```bash
docker compose -f doc/storage/docker-compose.elasticsearch.yml up -d
```

默认在 `.env` 中指向 `ES_HOST=localhost`、`ES_PORT=9200`（浏览器一般访问 **http://127.0.0.1:9200** 仅作健康检查；业务数据通过应用与脚本访问）。

**切分预览 Web（可选）**：依赖已包含在默认 `uv sync` 中。

```bash
uv run python -m chunking.webui
```

浏览器打开 **http://127.0.0.1:8765/**（无鉴权，仅本机调试）。等价：`uv run uvicorn chunking.webui.app:app --host 127.0.0.1 --port 8765`。

**问答 Web（RAG，可选）**：需已 `uv sync --extra embedding --extra llm`，并完成 `.env` 中与 LLM、ES、BGE 路径等配置。

```bash
uv run uvicorn qa.webui.app:app --host 127.0.0.1 --port 8766
```

浏览器打开 **http://127.0.0.1:8766/**。流式接口示例：`POST /api/qa/stream`（详见 [`doc/plan/v1.0.7-qa-webui-plan.md`](doc/plan/v1.0.7-qa-webui-plan.md)）。

**命令行脚本**（不入库/不问答时可不装 embedding/llm）：`uv run python scripts/rag_ingest.py`、`uv run python scripts/rag_qa.py "问题"` 等，见下文「本地开发」。

## 环境变量

- 复制 [`.env.example`](.env.example) 为项目根目录下的 `.env`，按注释填写。
- **勿将 `.env` 提交到仓库**；协作时只提交 `.env.example`（占位符，不含真实密钥）。
- 配置项说明与命名约定见 `src/conf/settings.py`（`conf` 包）。
- **日志（v1.1.0）**：`LOG_LEVEL`、`LOG_FORMAT`（`text` / `json`）、可选 `LOG_FILE`（相对路径相对项目根）。统一初始化与 uvicorn 拦截说明见 [`doc/plan/v1.1.0-logging-plan.md`](doc/plan/v1.1.0-logging-plan.md)。

## 本地开发

环境与 Web 启动见上文「环境配置与启动」。若不用 uv，也可用 pip 安装开发依赖后跑测试：

```bash
pip install -e ".[dev]"
pytest
```

**Elasticsearch**：`src/es_store` 使用 **`elasticsearch`** Python 客户端（已包含在 **`dev`** 可选依赖中；亦可单独 `pip install -e ".[es]"`）。本地集群示例：`docker compose -f doc/storage/docker-compose.elasticsearch.yml up -d`，再执行冒烟 `uv run python scripts/es_smoke_test.py`。索引命名见 [`doc/plan/v1.0.3-es-store-plan.md`](doc/plan/v1.0.3-es-store-plan.md)。

**入库（MVP）**：`data/*.md` 切分 → BGE-M3 → 写入 `ES_INDEX`（默认全量重建索引）。需已 `uv sync --extra embedding` 且 ES 可达。示例：`uv run python scripts/rag_ingest.py --dry-run`（仅统计块数）、`uv run python scripts/rag_ingest.py`。说明见 [`doc/plan/v1.0.4-ingest-plan.md`](doc/plan/v1.0.4-ingest-plan.md)（脚本名 **`rag_ingest.py`**，勿用 `ingest.py`，以免与 `src/ingest` 包冲突）。

**问答（MVP）**：单条问题走「查询向量 → ES kNN → system/user 提示 → OpenAI 兼容 `chat.completions`」。依赖：`uv sync --extra embedding --extra llm`，且 ES 已写入与入库一致的索引。示例：`uv run python scripts/rag_qa.py "你的问题"`；仅看拼接后的 messages（JSON）、不调 LLM：`uv run python scripts/rag_qa.py "问题" --dry-run`；检索条数覆盖：`--k 3`。实现见 [`doc/plan/v1.0.5-qa-plan.md`](doc/plan/v1.0.5-qa-plan.md)、[`src/qa/`](src/qa/)。

**导出 ES 块到 tmp**：将索引中与 `data/*.md` 同名的文档块读出，写入 `tmp/`（每块一行，块间空一行，相邻块重叠段用「【】」标出）：`uv run python scripts/es_dump_chunks_to_tmp.py`。

**LLM（OpenAI 兼容）**：连通性冒烟依赖可选组 **`llm`**（`openai`）。安装：`uv sync --extra llm`；若需同时保留向量编码依赖，可 `uv sync --extra embedding --extra llm`。配置好 `.env` 中 `MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME` 后执行 `uv run python scripts/llm_smoke_test.py`（会发起一次极短补全，产生少量费用）；仅检查配置加载可用 `uv run python scripts/llm_smoke_test.py --dry-run`。

**向量（BGE-M3）**：`src/embeddings` 依赖可选组 **`embedding`**（`FlagEmbedding`、`torch`、`numpy` 等；**`transformers` 锁定为 4.x**，与当前 `FlagEmbedding` 版本兼容）。仅跑切分/配置时可不装；需要本地编码时请执行 `uv sync --extra embedding`（默认已含 `dev`+`web`）或 `pip install -e ".[dev,web,embedding]"`。Apple Silicon 上是否走 **MPS**、以及编码前后参数所在设备，可运行 `uv run python scripts/bge_m3_device_check.py`（需 `.env` 中 `BGE_M3_PATH` 等到位才会加载模型）。**CPU 与 MPS 各约 10 条短句的耗时对比**（会加载两次模型）：`uv run python scripts/bge_m3_cpu_vs_mps_bench.py`。可选环境变量 **`BGE_EMBEDDING_DEVICE`** 强制设备（见 `.env.example`）。**MPS** 下构造后会做一次短句预热，避免首条在线请求承担权重从 CPU 迁到 GPU 的延迟。

**使用 uv 时**：`[dependency-groups]` 含 **`dev`**（pytest 等）与 **`web`**（FastAPI 等，跑 chunking WebUI 测试需要），**[tool.uv] default-groups** 为 `["dev","web"]`，因此 **`uv sync` 与 CI 的 `pip install -e ".[dev,web]"` 等价**，无需再写 `--extra dev` / `--extra web`。请同步并**用虚拟环境里的 pytest**，不要依赖 conda PATH 上的全局 `pytest`：

```bash
uv sync
uv run pytest
uv run pytest --cov=conf --cov=embeddings --cov=es_store --cov=qa --cov-report=term-missing --cov-report=xml --cov-fail-under=90
```

说明：若只执行裸 `uv sync` 且此前未配置 `default-groups`，会只装核心依赖，**不会**装 `dev`，`pytest` 会被卸掉；若仍出现该情况，请拉取本仓库最新 `pyproject.toml` 后再 `uv sync`。

**切分预览 Web（可选）**：本地人工验收滑窗效果，见 [`doc/chunk/Chunking 切分效果人工测试v01.md`](doc/chunk/Chunking%20切分效果人工测试v01.md)。可选勾选「句边界对齐」，规则见 [`doc/chunk/句边界对齐切分.md`](doc/chunk/句边界对齐切分.md)。默认已含 `web` 依赖；执行 `uv run python -m chunking.webui`，浏览器访问 `http://127.0.0.1:8765/`（无鉴权，仅本机调试）。等价命令：`uv run uvicorn chunking.webui.app:app --host 127.0.0.1 --port 8765`。

**问答 Web（可选）**：单轮 RAG、SSE 流式输出、分阶段耗时与 TTFT/总耗时。见 [`doc/plan/v1.0.7-qa-webui-plan.md`](doc/plan/v1.0.7-qa-webui-plan.md)。需 `uv sync --extra embedding --extra llm`。启动：`uv run uvicorn qa.webui.app:app --host 127.0.0.1 --port 8766`，浏览器打开 `http://127.0.0.1:8766/`。API：`POST /api/qa/stream`（JSON：`query`、`k` 可选、`max_tokens`、`conversation_id` 预留多轮）。**性能**：embedder 等在进程内单例预加载（见 [`doc/plan/v1.0.8-qa-webui-performance-plan.md`](doc/plan/v1.0.8-qa-webui-performance-plan.md)）；多 worker 时每个进程各加载一份模型，显存与首包延迟会成倍增加，**生产环境建议 `--workers 1`**，除非你能接受多份权重或改用进程外向量服务。

或 `source .venv/bin/activate` 后再执行 `pytest ...`。若直接输入 `pytest` 而 `command -v pytest` 指向 `/opt/anaconda3/bin/pytest`，即使用 `uv add pytest-cov` 装进了 `.venv`，也会出现 `--cov` 无法识别（实际跑的是 conda 的 pytest）。

---

仅跑用例时，安装 `pytest` 即可（`pip install pytest`）。**覆盖率**需要 **`pytest-cov`**（`pip install pytest-cov` 或 `pip install -e ".[dev]"` / `uv sync --extra dev`）；未安装时若使用 `--cov` 会报 `unrecognized arguments`。带覆盖率与 `conf` 包 **90%** 门槛时：

```bash
pip install -e ".[dev]"
pytest --cov=conf --cov=embeddings --cov=es_store --cov=qa --cov-report=term-missing --cov-report=xml --cov-fail-under=90
```

- 配置相关测试位于 [`tests/test_conf/test_settings.py`](tests/test_conf/test_settings.py)（对应 `src/conf/settings.py`）。目录故意命名为 `test_conf`，避免使用 `tests/conf/` 与 Python 包 `conf` 同名导致导入被遮蔽。
- 覆盖率相关选项写在 `pyproject.toml` 注释与 CI 脚本中；`[tool.coverage.*]` 供 `pytest-cov` 使用。
- pytest 运行用例时会设置 `PYTEST_CURRENT_TEST`，此时 **不会读取项目根 `.env`**，仅使用进程环境（测试中通过 `monkeypatch` 注入），避免本机密钥干扰断言。正常运行应用时仍会加载 `.env`。

## CI

- **GitHub Actions**：推送或 PR 至 `main` / `master` 时运行，见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)（Python 3.11；`actions/checkout@v6`、`actions/setup-python@v6`）。**工作流成功/失败通知**（邮件、站内等）见 [`doc/cicd/README.md`](doc/cicd/README.md) 中「工作流成功/失败如何收到通知」。
- **GitLab CI**：见根目录 [`.gitlab-ci.yml`](.gitlab-ci.yml)。

在 CI 中请勿写入真实 API Key；若日后做集成测试，请使用仓库 **Secrets** 注入环境变量。

## 许可证

见仓库内 `LICENSE`（若存在）。
