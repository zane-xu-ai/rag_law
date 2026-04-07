# 新增 Markdown 文档：切分、向量化、写入 Elasticsearch

本文说明如何把**新增或更新的**法规 Markdown（例如 [`data/md3/民法典.md`](../../data/md3/民法典.md)）经切分、BGE-M3 向量化后写入 ES，与 [`scripts/rag_ingest.py`](../../scripts/rag_ingest.py) 行为一致。

## 前置条件

- 已安装依赖：`uv sync --extra embedding`（向量模型），本机 Elasticsearch 可访问。
- 环境变量 / `.env`：`BGE_M3_PATH`、`ES_*` 等与现有入库一致（见仓库 README、[doc/storage/docker-compose.elasticsearch.yml](../../doc/storage/docker-compose.elasticsearch.yml)）。
- 数据目录约定：入库脚本对 `--data-dir` 使用 **`*.md` 仅该目录下一层**（[`src/ingest/loaders.py`](../../src/ingest/loaders.py) 中 `base.glob("*.md")`），**不递归子目录**。因此 `data/md3/民法典.md` 会被扫描；`data/md3/sub/foo.md` 不会。

## 推荐流程（示例：使用 `data/md3`）

在项目根执行：

```bash
# 可选：先看块数、不连模型与 ES
uv run python scripts/rag_ingest.py --data-dir data/md3 --dry-run

# 正式入库（默认会删索引后重建，见下文「重建与增量」）
uv run python scripts/rag_ingest.py --data-dir data/md3
```

### 指定单个或多个文件（例如仅 `data/md4/民法典.md`）

与 `--data-dir` **二选一**，使用 `--files`，路径相对**项目根**或绝对路径：

```bash
uv run python scripts/rag_ingest.py --files data/md4/民法典.md --dry-run
# 增量写入已有索引（不删库）
uv run python scripts/rag_ingest.py --files data/md4/民法典.md --no-recreate
```

若目录 `data/md4/` 下**只有**该文件，也可用 `--data-dir data/md4`，效果等价于只处理这一份 `*.md`。

可选参数：

- `--no-recreate`：不删除已有索引，仅在当前映射下 **bulk 写入/覆盖**（见下文）。
- `--boundary-aware`：句边界对齐切分（与默认滑窗不同，按需开启）。
- `--smoke-query ""`：跳过入库后的 kNN 抽检。

若 `md2` 产出物需先汇总到 `md3`，可执行：

```bash
uv run python scripts/export_md2_full_to_md3.py
```

（见此前「md2 → md3」脚本说明。）

## 脚本在做什么（与「计划」对应）

1. **切分**：`load_chunks_with_sha256` 读取目录内所有 `*.md`，按 `chunk_size` / `chunk_overlap` 等（来自 [`conf/settings`](../../src/conf/settings.py)）切成 `TextChunk`，并记录每文件 SHA256。
2. **向量化**：`build_embedder` → `embed_documents` 对全部 chunk 文本编码。
3. **写入 ES**：`EsChunkStore.ensure_index` + `bulk_index_chunks`；文档 `_id` 为 **`{source_file}:{chunk_index}`**，其中 `source_file` 为 **文件名**（如 `民法典.md`），见 [`es_store/store.py`](../../src/es_store/store.py) 中 `chunk_document_id`。

## 重建与增量（必读）

| 方式 | 命令要点 | 适用 |
| --- | --- | --- |
| **全量重建索引** | 默认 `--recreate`（删索引再建再 bulk） | 希望索引内容与某一目录下全部 `*.md` **完全一致**，避免遗留旧块。 |
| **不删索引** | `--no-recreate` | 在已有索引上**追加或覆盖**本次扫描到的 chunk。 |

注意：

- **同文件名冲突**：`_id` 只依赖 `source_file`（文件名）与 `chunk_index`，与文件在 `data/` 还是 `data/md3/` **无关**。若索引里已有来自 `data/民法典.md` 的块，再只对 `data/md3/民法典.md` 入库且 **`--no-recreate`**，相同 `chunk_index` 会被**覆盖**；若新文件块数**少于**旧文件，**多出来的旧 chunk 不会自动删除**，可能残留脏数据。此时应使用 **`--recreate` 并对「希望进索引的全部法规」统一放在一个目录后一次入库**，或自行在 ES 中删除该 `source_file` 相关文档后再增量写入。
- **仅一条新文件**：可建临时目录只放该 `*.md`，`--data-dir` 指向该目录；若与库内已有法规**文件名不同**，增量一般只新增文档，冲突风险低。

## 仅验证「民法典」一条时的做法

- 若 `data/md3` 下只有（或你暂时只关心）`民法典.md`，仍用 `--data-dir data/md3`；若目录内还有其他 `.md`，脚本会**一并**切分入库。
- 若只想单文件又不想动同目录其他文件：复制 `民法典.md` 到单独目录（例如 `data/inbox/`）且该目录仅含此文件，再 `--data-dir data/inbox`，并结合上表选择 `--recreate` 或 `--no-recreate`。

## 与 `data/` 根目录平铺 Markdown 的关系

默认 `rag_ingest.py` 不传参时 `--data-dir` 为项目根下 **`data`**（即扫描 `data/*.md`，**不包含** `data/md3/`）。因此：

- 使用 **`data/md3`** 作为数据源时，必须显式传入 **`--data-dir data/md3`**。
- 若历史上用 `data/*.md` 建过索引，再切换到只维护 `md3`，建议理清「全量来源目录」并用 **`--recreate`** 做一次一致的全量，避免同名文件跨路径造成理解偏差。

## 相关文档

- 入库与索引设计：[doc/plan/v1.0.4-ingest-plan.md](../plan/v1.0.4-ingest-plan.md)
- ES 映射与 store：[doc/plan/v1.0.3-es-store-plan.md](../plan/v1.0.3-es-store-plan.md)
