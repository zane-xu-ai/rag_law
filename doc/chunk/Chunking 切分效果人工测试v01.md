# Chunking 切分效果人工测试（v01 说明文档）

| 属性 | 说明 |
| --- | --- |
| 文档版本 | v01 |
| 状态 | 已实现预览页（代码在 [src/chunking/webui](../../src/chunking/webui/)） |
| 关联切分逻辑 | [src/chunking/split.py](../../src/chunking/split.py)（`iter_text_slices` / `iter_chunks_for_text`） |

---

## 1. 目标

提供**本地开发用** Web 界面，用于人工验收字符滑窗切分效果：

- 用户可**输入文本**，或**上传文本文件**（UTF-8）。
- 用户可设置 `chunk_size`、`chunk_overlap`（与配置语义一致：`overlap < size`）。
- 点击「切分」后展示：
  - **汇总信息**：如总字符数、块数、配置参数、每段字符数分布、相邻块实际重叠等。
  - **每段正文**：若块数超过 **15**，仅展示**前 5 段、中间 5 段、后 5 段**（共 15 段），并明确提示总块数与省略情况。

本页**不参与**向量检索、Elasticsearch 或 LLM，仅用于调试切分。

---

## 2. 代码目录约定

与切分预览相关的 Web 资源统一放在 **[src/chunking/webui/](../../src/chunking/webui/)**（不使用 `chunking/static` 等易混淆路径）。

| 路径 | 职责 |
| --- | --- |
| [preview_logic.py](../../src/chunking/webui/preview_logic.py) | 纯函数：相邻块重叠长度、`pick_display_indices`（块数大于 15 时的展示下标）、原文段落粗分、`MAX_PREVIEW_BYTES`（正文 UTF-8 体积上限） |
| [app.py](../../src/chunking/webui/app.py) | FastAPI 应用：`POST /api/preview`、`GET /api/health`；将 `webui/static/` 挂载到站点根路径 `/` |
| [static/](../../src/chunking/webui/static/) | 单页 `index.html`、`styles.css`、`app.js` |
| [__main__.py](../../src/chunking/webui/__main__.py) | `python -m chunking.webui` 时启动 Uvicorn（默认 `127.0.0.1:8765`） |
| [__init__.py](../../src/chunking/webui/__init__.py) | 导出 `app`，供 `uvicorn chunking.webui.app:app` 使用 |

---

## 3. 技术选型

| 项目 | 建议 | 理由 |
| --- | --- | --- |
| 后端 | FastAPI + Uvicorn | 与项目已有 `pydantic` 一致；JSON API 清晰；可挂载静态目录；便于用 `TestClient` 写测试。 |
| 前端 | 单页 HTML + 原生 JavaScript | 无构建链路，与当前仓库形态匹配，改完即可本地验证。 |
| 切分 | 直接调用 `iter_chunks_for_text`（或底层 `iter_text_slices`） | 与生产路径一致，避免重复实现滑窗。 |

**依赖管理**：在 [pyproject.toml](../../pyproject.toml) 的 **`[project.optional-dependencies] web`** 中声明：`fastapi`、`uvicorn[standard]`、`httpx`（`TestClient`）、`python-multipart`（解析 multipart 表单）。默认安装不包含该组；使用预览页或跑相关测试时需安装，例如 `pip install -e ".[web]"` 或 `uv sync --extra web`（开发时常与 `dev` 一并安装）。

---

## 4. 指标与用语（避免歧义）

当前 [split.py](../../src/chunking/split.py) 为**字符滑窗**，没有语言学上的「段落」切分。文档与界面建议区分：

| 用语 | 含义 |
| --- | --- |
| **块数** | 滑窗产生的段数，即 `len(chunks)`。 |
| **原文段落数（可选）** | 对原文按空行等规则粗分的段落个数，**仅展示参考**，不参与切分算法。 |
| **配置重叠** | 用户传入的 `chunk_overlap`（字符数）。 |
| **相邻块实际重叠** | 根据相邻两块的 `char_start` / `char_end` 推导的字符层面重叠长度，用于核对是否与配置一致（文末最后一块可能小于配置步长带来的重叠表现，需在说明中允许例外）。 |

汇总区建议至少包含：**总字符数**、**块数**、`chunk_size` / `chunk_overlap`、每块字符数 **min / max / avg**、相邻重叠 **min / max**（块数至少为 2 时）。

---

## 5. API 草案（后端）

- **`POST /api/preview`**
  - **JSON**：`text`、`chunk_size`、`chunk_overlap`（整数；服务端校验 `overlap < size`）；可选 **`boundary_aware`**（布尔，默认 `false`）：为 `true` 时使用 [句边界对齐切分.md](句边界对齐切分.md) 规则（见 `chunking.boundary`）。
  - **multipart**：可选上传 `file`；若表单中 `text` 为空，则用上传文件按 **UTF-8** 解码（解码失败返回 4xx 并给出明确错误信息）。
  - **体积上限**：实现为 UTF-8 编码后不超过 **3 MiB**（`preview_logic.MAX_PREVIEW_BYTES`）；超限返回 413。

- **响应 JSON（实现字段）**
  - `summary`：`total_chars`、`chunk_count`、`chunk_size`、`chunk_overlap`、**`boundary_aware`**（是否启用句边界对齐）、`chars_per_chunk`（各块长度列表）、`chars_per_chunk_stats`（`min` / `max` / `avg`，无块时为 `null`）、`overlap_between_adjacent`（相邻块重叠长度列表）、`overlap_adjacent_stats`（同上，少于两块时为 `null`）、`source_paragraphs`（原文按空行粗分的段落数）。
  - `display`：`mode` 为 `full` 或 `truncated`；`total_chunks`；`omitted_message`（截断时的说明文案，否则为 `null`）；`chunks`：每项含 `index`、`text`、`char_start`、`char_end`、`section`（`all` / `first` / `middle` / `last`，便于前端分组标签）。

---

## 6. 分段展示规则（与需求对齐）

- 当 **块数 ≤ 15**：返回并展示**全部**块。
- 当 **块数 > 15**：仅展示 **前 5 段、中间 5 段、后 5 段**（共 15 条）。中间 5 段下标由 [preview_logic.pick_display_indices](../../src/chunking/webui/preview_logic.py) 固定（`mid_start = max(5, min(n - 10, n // 2 - 2))` 起连续 5 个下标）。响应与界面写明「共 N 段，仅展示前/中/后各 5 段」。

---

## 7. 安全与运行方式

- 默认面向 **本机调试**；通过 `127.0.0.1` 访问；若需局域网访问，应自行评估风险（**无鉴权**）。
- **启动**（需安装 `web` 额外依赖：`pip install -e ".[web]"` 或 `uv sync --extra web`）：
  - `uv run python -m chunking.webui`（默认 `127.0.0.1:8765`）
  - 或 `uv run uvicorn chunking.webui.app:app --host 127.0.0.1 --port 8765`
- 浏览器打开 `http://127.0.0.1:8765/` 使用单页界面；API 为 `POST /api/preview`、`GET /api/health`。

---

## 8. 测试与 CI

- **单测位置**
  - [tests/test_chunking/test_preview_logic.py](../../tests/test_chunking/test_preview_logic.py)：`preview_logic` 中重叠、展示下标、段落计数等纯函数。
  - [tests/test_chunking/test_webui_preview.py](../../tests/test_chunking/test_webui_preview.py)：`TestClient` 覆盖 JSON 与 multipart、`/api/health`、首页 HTML、块数大于 15 的截断、`boundary_aware`、非法 `Content-Type` 等。
  - [tests/test_chunking/test_boundary.py](../../tests/test_chunking/test_boundary.py)：句边界 `adjust_start` / `adjust_end`、`iter_text_slices_boundary_aware` 与 `iter_chunks_for_text(boundary_aware=True)`。
- **CI**：GitHub Actions（[.github/workflows/ci.yml](../../.github/workflows/ci.yml)）与 GitLab CI（[.gitlab-ci.yml](../../.gitlab-ci.yml)）在安装依赖时使用 **`pip install -e ".[dev,web]"`**，以便上述测试在流水线中可直接运行，无需单独可选步骤。

---

## 9. 非目标（v01 不包含）

- 用户鉴权、HTTPS、生产级部署。
- 接入向量模型、Elasticsearch、PDF 解析。
- 预览页可通过 `boundary_aware` 调用句边界对齐；**默认仍为纯滑窗**，与 `iter_chunks_for_text` 默认参数一致。

---

## 10. 实施顺序（v01 已完成）

1. 已增加 `web` optional 依赖，并在 `src/chunking/webui/` 下提供入口与静态页。
2. 已实现 `POST /api/preview`、汇总统计与块数大于 15 时的截断逻辑。
3. 已完成前端：文本框、文件上传、参数、汇总与分段展示。
4. 已补充单测、CI 安装 `dev,web`，并在 [README.md](../../README.md) 中写明启动方式。

---

## 11. 实现说明（速览）

以下为与当前仓库实现一致的摘要，便于查阅与交接。

### 11.1 模块与职责

| 组件 | 说明 |
| --- | --- |
| `preview_logic.py` | 相邻块重叠、`pick_display_indices`、原文段落粗分、单次请求 3 MiB 上限常量 |
| `app.py` | FastAPI 路由、`iter_chunks_for_text` 切分、JSON/multipart 两种 `POST /api/preview`、`GET /api/health`、静态资源挂载 |
| `static/` | 单页界面：文本或上传 UTF-8 文件、`chunk_size` / `chunk_overlap`、切分结果展示 |
| `__main__.py` | `python -m chunking.webui` 启动 Uvicorn，默认监听 `127.0.0.1:8765` |

### 11.2 依赖

- 见 [pyproject.toml](../../pyproject.toml) 中 **`[project.optional-dependencies] web`**：`fastapi`、`uvicorn[standard]`、`httpx`、`python-multipart`。

### 11.3 测试与 CI

- 测试文件见上文 §8；全量 `pytest` 包含 chunking 相关用例。
- CI 使用 **`pip install -e ".[dev,web]"`**（见 `.github/workflows/ci.yml`、`.gitlab-ci.yml`）。

### 11.4 本地运行

```bash
uv sync --extra dev --extra web
uv run python -m chunking.webui
```

浏览器访问 `http://127.0.0.1:8765/`。等价命令：`uv run uvicorn chunking.webui.app:app --host 127.0.0.1 --port 8765`。

**注意**：服务无鉴权，仅用于本机调试，勿暴露到公网。

---

## 12. 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v01 | 2026-04 | 切分预览页目标与规格；实现落地后的目录表、API 字段、测试与 CI、§10–§11 与修订说明。 |
