# rag_law

法律类 RAG（MVP）：文档切分、向量检索、LLM 问答。详见 [`doc/plan/v1.0.0-rag-law-mvp-plan.md`](doc/plan/v1.0.0-rag-law-mvp-plan.md)。

## 环境变量

- 复制 [`.env.example`](.env.example) 为项目根目录下的 `.env`，按注释填写。
- **勿将 `.env` 提交到仓库**；协作时只提交 `.env.example`（占位符，不含真实密钥）。
- 配置项说明与命名约定见 `src/conf/settings.py`（`conf` 包）。

## 本地开发

```bash
pip install -e ".[dev]"
pytest
```

**使用 uv 时**：开发依赖在 `[project.optional-dependencies] dev`。请同步并**用虚拟环境里的 pytest**，不要依赖 conda PATH 上的全局 `pytest`：

```bash
uv sync --extra dev
uv run pytest
uv run pytest --cov=conf --cov-report=term-missing --cov-report=xml --cov-fail-under=90
```

**切分预览 Web（可选）**：本地人工验收滑窗效果，见 [`doc/chunk/Chunking 切分效果人工测试v01.md`](doc/chunk/Chunking%20切分效果人工测试v01.md)。可选勾选「句边界对齐」，规则见 [`doc/chunk/句边界对齐切分.md`](doc/chunk/句边界对齐切分.md)。需额外安装 `web` 依赖：`uv sync --extra dev --extra web`，再执行 `uv run python -m chunking.webui`，浏览器访问 `http://127.0.0.1:8765/`（无鉴权，仅本机调试）。等价命令：`uv run uvicorn chunking.webui.app:app --host 127.0.0.1 --port 8765`。

或 `source .venv/bin/activate` 后再执行 `pytest ...`。若直接输入 `pytest` 而 `command -v pytest` 指向 `/opt/anaconda3/bin/pytest`，即使用 `uv add pytest-cov` 装进了 `.venv`，也会出现 `--cov` 无法识别（实际跑的是 conda 的 pytest）。

---

仅跑用例时，安装 `pytest` 即可（`pip install pytest`）。**覆盖率**需要 **`pytest-cov`**（`pip install pytest-cov` 或 `pip install -e ".[dev]"` / `uv sync --extra dev`）；未安装时若使用 `--cov` 会报 `unrecognized arguments`。带覆盖率与 `conf` 包 **90%** 门槛时：

```bash
pip install -e ".[dev]"
pytest --cov=conf --cov-report=term-missing --cov-report=xml --cov-fail-under=90
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
