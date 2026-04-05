# 测试与 CI/CD 说明

本文档整理本仓库中与**自动化测试**、**覆盖率**、**持续集成**及**环境变量规范**相关的约定与文件位置。

---

## 1. 测试布局

| 路径 | 说明 |
| --- | --- |
| [`tests/conftest.py`](../../tests/conftest.py) | 公共 fixture：每个用例前后清理 `get_settings` 的 `lru_cache`；将 [`src`](../../src) 加入 `sys.path`，便于在未执行 `pip install -e .` 时也能 `import conf`。 |
| [`tests/test_conf/test_settings.py`](../../tests/test_conf/test_settings.py) | 针对 [`src/conf/settings.py`](../../src/conf/settings.py) 的单元测试（环境变量、别名、校验、`es_url` 等）。 |

**目录为何叫 `test_conf` 而非 `tests/conf`**

- 源码包名为 [`conf`](../../src/conf)。pytest 会把测试相关路径加入 `sys.path`；若存在目录 `tests/conf/`，可能被当作顶层包 `conf`，**遮蔽** `src/conf`，导致 `from conf.settings import ...` 失败（例如 `No module named 'conf.settings'`）。
- 因此测试目录使用 **`tests/test_conf/`**，与 `src/conf` 对应但不同名，避免导入冲突。

---

## 2. pytest 与覆盖率

- **依赖**：开发依赖见 [`pyproject.toml`](../../pyproject.toml) 中 `[project.optional-dependencies] dev`（含 `pytest`、`pytest-cov`）。
- **仅跑测试**（不要求已装 `pytest-cov`）：

  ```bash
  pip install pytest
  pytest
  ```

- **带覆盖率与 `conf` 包 90% 门槛**（需 `pytest-cov`，已包含在 `dev` 中）：

  ```bash
  pip install -e ".[dev]"
  pytest --cov=conf --cov-report=term-missing --cov-report=xml --cov-fail-under=90
  ```

  默认不在 `pyproject.toml` 的 `addopts` 里写 `--cov`，避免环境里只有 `pytest`、未装 `pytest-cov` 时出现 `unrecognized arguments: --cov=...`。

- **配置位置**：[`pyproject.toml`](../../pyproject.toml) 中 `[tool.pytest.ini_options]`、`[tool.coverage.run]`、`[tool.coverage.report]`（`pytest-cov` 读取后者）。
- **覆盖率范围**：`--cov=conf`，仅统计 **`src/conf`**；**门槛 90%**（`--cov-fail-under=90`）。
- **报告**：终端 missing 行 + `coverage.xml`（已在 [`.gitignore`](../../.gitignore) 中忽略）。

---

## 3. 配置加载与 pytest 行为

[`src/conf/settings.py`](../../src/conf/settings.py) 中通过 **`settings_customise_sources`** 处理：

- **正常运行**：按顺序加载初始化参数、环境变量、**`.env` 文件**、secrets 等（与 pydantic-settings 默认行为一致，项目根 `.env` 见 `model_config`）。
- **pytest 执行用例时**：环境变量中存在 **`PYTEST_CURRENT_TEST`**（pytest 自动设置），此时**跳过**对项目根 `.env` 的读取，仅依赖**进程环境变量**。测试中通过 **`monkeypatch.setenv`** 注入完整变量，避免开发者本机 `.env` 中的真实密钥干扰断言。

---

## 4. 环境变量与密钥

| 事项 | 说明 |
| --- | --- |
| 模板 | 根目录 [`.env.example`](../../.env.example)：占位符与注释，**不含真实密钥**；顶部列出 MVP **必填项**（`MODEL_*`、`BGE_M3_PATH` 等）。 |
| 本地使用 | 复制为项目根目录下的 `.env` 并填写真实值。 |
| 版本库 | **勿提交 `.env`**（已在 `.gitignore` 中忽略）；协作只提交 `.env.example`。 |
| 配置实现 | 字段与别名见 [`src/conf/settings.py`](../../src/conf/settings.py)。 |

---

## 5. 持续集成（CI）

### GitHub Actions

- 工作流文件：[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)。
- **触发**：推送到 `main` / `master`，或针对这两支的 **Pull Request**。
- **矩阵**：Python **3.11**。
- **步骤**：检出代码 → 安装 Python（pip 缓存）→ `pip install -e ".[dev]"` → 带覆盖率参数执行 `pytest`（与上文「带覆盖率」命令一致）。
- **官方 Action 版本**：使用 `actions/checkout@v6`、`actions/setup-python@v6`（基于 Node.js 24 运行时），可减少 GitHub 关于「Node.js 20 Action 弃用」的日志警告；若日后官方推荐更新主版本，可同步升级并查看各 Action 的 Release 说明。

#### 工作流成功/失败如何收到通知

通知在 **GitHub 账号侧** 配置，仓库 YAML 默认不会单独发邮件。

| 方式 | 说明 |
| --- | --- |
| 站内 | 登录 GitHub 后右上角铃铛；对仓库 **Watch** 并在 [Notifications](https://github.com/settings/notifications) 中勾选与 **Actions** 相关的选项。 |
| 邮件 | 打开 **Settings → Notifications**（个人设置），在 **Actions** 区域勾选工作流运行通知（可按「仅失败」等偏好调整）。 |
| 手机 | 安装 GitHub Mobile 并开启推送（仍受上述通知偏好约束）。 |
| 第三方 | 在工作流中增加步骤，通过 Webhook 推送到 Slack/飞书/钉钉等（需自行保管 URL 与密钥）。 |

团队场景可在频道侧接 Webhook；个人仓库通常 **邮件 + 站内** 即可。

### GitLab CI

- 配置文件：根目录 [`.gitlab-ci.yml`](../../.gitlab-ci.yml)。
- 镜像：`python:3.11`；`before_script` 中 `pip install -e ".[dev]"`，`test` 作业执行与 GitHub 相同的带覆盖率 `pytest` 命令。

两套流水线二选一或并行使用均可；**不要在 YAML 中硬编码真实 API Key**；若日后需要密钥类集成测试，应使用平台提供的 **Secrets / CI 变量** 注入。

---

## 6. 相关文件索引

| 文件 | 作用 |
| --- | --- |
| [`pyproject.toml`](../../pyproject.toml) | 包元数据、`dev` 可选依赖、pytest/coverage 配置 |
| [`.env.example`](../../.env.example) | 环境变量模板与必填项说明 |
| [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) | GitHub Actions |
| [`.gitlab-ci.yml`](../../.gitlab-ci.yml) | GitLab CI |
| [`README.md`](../../README.md) | 项目入口说明（含测试与 CI 简要指引） |

---

## 7. 常见问题

### `pytest: error: unrecognized arguments: --cov=...`

**原因 A：未安装 `pytest-cov`**（`--cov` 由该插件注册）。任选其一：

```bash
pip install pytest-cov
# 或
pip install -e ".[dev]"
```

**原因 B：已用 `uv`/`pip` 装进项目 `.venv`，但终端里执行的 `pytest` 不是虚拟环境里的**（常见于 conda `base` 在 PATH 最前）。本机可对比：

```bash
command -v pytest          # 若为 /opt/anaconda3/bin/pytest 等，即 conda 全局
uv run which pytest        # 应为 项目/.venv/bin/pytest
```

请任选其一再跑带 `--cov` 的命令：

- `uv sync --extra dev && uv run pytest --cov=conf ...`
- 或 `source .venv/bin/activate` 后再 `pytest --cov=conf ...`

仅使用「裸」`pytest` 且 PATH 指向 conda 时，即使用 `uv add pytest-cov` 装进了 `.venv`，仍会报 unrecognized arguments。

### Pydantic `Field "model_*" has conflict with protected namespace "model_"`

已在 [`src/conf/settings.py`](../../src/conf/settings.py) 的 `SettingsConfigDict` 中设置 `protected_namespaces=('settings_',)`，避免合法字段名 `model_api_key` 等与保留前缀冲突。若仍见警告，请确认 pydantic 版本为 v2。

---

## 8. 维护提示

- 向 `src/conf` 增加逻辑时，同步补充 [`tests/test_conf/test_settings.py`](../../tests/test_conf/test_settings.py)，并关注覆盖率是否仍满足 **90%** 门槛。
- 调整 CI 矩阵（例如新增 Python 3.13）时，同时更新 **GitHub** 与 **GitLab** 配置（若两者均在用）。

