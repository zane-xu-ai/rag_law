# Chunking 切分效果人工测试（v01 说明文档）

| 属性 | 说明 |
| --- | --- |
| 文档版本 | v01 |
| 状态 | 规格说明（实现代码后续落在 [src/chunking/webui](../../src/chunking/webui/)） |
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

实现时，与切分相关的 Web 资源统一放在仓库内目录：

**[src/chunking/webui/](src/chunking/webui/)**

建议布局（实施阶段参考，v01 文档不展开具体文件名以外的约束）：

- 后端入口（如 FastAPI 应用模块）与路由。
- 静态前端（HTML / CSS / JS），可由同一进程通过静态文件挂载提供。

与早期草稿中「`chunking/static`」类路径的表述对齐为：**统一使用 `webui` 子目录**，避免与将来其他静态资源混淆。

---

## 3. 技术选型

| 项目 | 建议 | 理由 |
| --- | --- | --- |
| 后端 | FastAPI + Uvicorn | 与项目已有 `pydantic` 一致；JSON API 清晰；可挂载静态目录；便于用 `TestClient` 写测试。 |
| 前端 | 单页 HTML + 原生 JavaScript | 无构建链路，与当前仓库形态匹配，改完即可本地验证。 |
| 切分 | 直接调用 `iter_chunks_for_text`（或底层 `iter_text_slices`） | 与生产路径一致，避免重复实现滑窗。 |

**依赖管理**：将 `fastapi`、`uvicorn[standard]` 放入 `pyproject.toml` 的 **optional-dependencies**（例如名为 `web` 的额外组），默认安装保持精简；文档与 README 中说明预览功能需安装该额外依赖。

---

## 4. 指标与用语（避免歧义）

当前 [split.py](src/chunking/split.py) 为**字符滑窗**，没有语言学上的「段落」切分。文档与界面建议区分：

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
  - **JSON**：`text`、`chunk_size`、`chunk_overlap`（整数；服务端校验 `overlap < size`）。
  - **multipart**：可选上传 `file`；若表单中 `text` 为空，则用上传文件按 **UTF-8** 解码（解码失败返回 4xx 并给出明确错误信息）。
  - **体积上限**：限制请求体或文件大小（例如 2～5 MB 量级），避免单次请求占用过多内存。

- **响应 JSON（逻辑字段）**
  - `summary`：`total_chars`、`chunk_count`、`chunk_size`、`chunk_overlap`、每块字符数列表或聚合、`overlap_between_adjacent`（列表）、可选 `source_paragraphs`。
  - `display`：`mode` 为 `full` 或 `truncated`；`chunks` 为展示用块列表（含 `index`、`text`、`char_start`、`char_end`）；若为 `truncated`，附带 `total_chunks` 与省略说明文案。

具体字段名可在实现时微调，但与上述语义保持一致。

---

## 6. 分段展示规则（与需求对齐）

- 当 **块数 ≤ 15**：返回并展示**全部**块。
- 当 **块数 > 15**：仅展示 **前 5 段、中间 5 段、后 5 段**（共 15 条）。中间 5 段的索引规则需在实现时固定（例如围绕中心索引对称取 5 个），并在界面写明「共 N 段，仅展示前/中/后各 5 段」。

---

## 7. 安全与运行方式

- 默认面向 **本机调试**；通过 `127.0.0.1` 或文档给出的端口访问；若需局域网访问，应在文档中提示风险（无鉴权）。
- 启动方式示例（实现后写入 README 或本文后续版本）：`uvicorn ...` 或 `python -m chunking.webui`（具体模块名以代码为准）。

---

## 8. 测试与 CI

- 使用 FastAPI `TestClient`（或 `httpx`）对 `/api/preview` 编写自动化测试：短文本全量展示、构造长文本使块数大于 15 并断言截断结构。
- 可选：对「相邻块重叠长度」计算抽取为纯函数并单测。
- CI 中若默认环境不安装 `web` 额外依赖，需 **`uv sync --extra web`**（或等价命令）后再跑相关测试，或将 Web 测试单独标记为可选任务。

---

## 9. 非目标（v01 不包含）

- 用户鉴权、HTTPS、生产级部署。
- 接入向量模型、Elasticsearch、PDF 解析。
- 修改 [split.py](src/chunking/split.py) 的滑窗算法（预览页只消费现有 API）。

---

## 10. 建议实施顺序

1. 增加 optional 依赖；在 `src/chunking/webui/` 下建立应用入口与静态资源占位，本地能打开页面。
2. 实现 `POST /api/preview`、汇总统计与「大于 15 段」的截断逻辑。
3. 完成前端：文本框、上传、参数、结果渲染。
4. 补充测试与 CI、文档中的启动命令。

---

## 11. 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v01 | 2026-04 | 初稿：整理切分预览页目标、目录 `webui`、选型、API 与展示规则。 |
