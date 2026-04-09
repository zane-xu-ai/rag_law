# 入库（Ingest）执行手册：分步操作与 Elasticsearch 验证

- **教学向**（短样例、`chunk_version`、删除旧版本演示）：**[c05_ingest_es_runbook.ipynb](c05_ingest_es_runbook.ipynb)**  
- **生产向**（真实 OSS 列举/下载、**入库前 ES 范围预览**、按 `source_path` 精确删除再 bulk）：**[c06_oss_ingest.ipynb](c06_oss_ingest.ipynb)**

本文档与 [doc/plan/v1.0.4-ingest-plan.md](../doc/plan/v1.0.4-ingest-plan.md) 对应，面向**手工按步骤执行**入库与**数据库（Elasticsearch）侧验证**。项目里「数据库」指 **ES 中的 chunk 索引**（默认名见环境变量 `ES_INDEX`，常为 `rag_law_doc_chunks`），不是 MySQL。

---

## 0. 阅读前必读：为什么会产生「旧 chunk 残留」

### 0.1 文档 `_id` 的生成规则

入库时每条 chunk 在 ES 中的文档 ID 为（见 [`src/es_store/store.py`](../src/es_store/store.py)）：

```text
_id = "{source_file}:{chunk_index}"
```

- `source_file`：来自切分后的 `TextChunk.source_file`，一般为 **Markdown 文件名**（如 `宪法.md`），不是完整路径。
- `chunk_index`：该文件内从 0 递增的块序号。

**同一 `_id` 再次 `index` 会覆盖**旧文档；**若旧索引里存在某个 `_id`，而本次入库不再生成该 `_id`**，则除非显式删除，否则该文档会**一直留在索引里**。

### 0.2 典型残留场景

| 场景 | 是否容易残留 |
| --- | --- |
| 某文件本次切分块数 **变少**（参数变更、换 shorter 文本） | **会**：例如过去有 `foo.md:0`…`foo.md:99`，本次只有 50 块，则 `foo.md:50`…`foo.md:99` 仍为旧数据 |
| 某文件 **改名** 或 `source_file` 变化 | **会**：旧 `旧名.md:*` 全部残留 |
| 从「多文件」改为「少文件」入库 | **会**：未被覆盖的 `source_file` 整组残留 |
| 使用 **`--recreate`（删索引重建）** | **不会**（索引清空后只有本次 bulk 的文档） |

因此：**要保证「索引里没有任何与本次语料无关的旧 chunk」**，要么 **整索引重建**，要么在入库前/后做 **按条件的删除**（见下文 §5）。

---

## 1. 前置条件检查清单

在**项目根目录**执行（以下路径均以仓库根为当前工作目录）。

### 1.1 依赖与配置

1. 安装（本地入库至少 embedding + es；OSS 入库再加 oss）：

   ```bash
   uv sync --extra embedding --extra es
   # OSS 来源时：
   # uv sync --extra oss --extra embedding --extra es
   ```

2. 确认 `.env`（或环境变量）中至少包含：
   - **LLM / 向量**：`MODEL_*`、`BGE_M3_PATH` 等（与 [`src/conf/settings.py`](../src/conf/settings.py) 一致）。
   - **ES**：`ES_HOST`、`ES_PORT`、`ES_INDEX`；若集群启用安全则 `ES_USER`、`ES_PASSWORD`、`ES_USE_SSL`。
   - **OSS 入库额外**：`OSS_REGION`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`；可选 `OSS_BUCKET`、`OSS_OBJECT_PREFIX`。

3. **Elasticsearch 进程已启动且可达**（例如本机 Docker，见 `doc/storage/docker-compose.elasticsearch.yml`）。

### 1.2 连通性验证（建议先做）

```bash
# 若项目提供 smoke 脚本可一并使用；至少应能 ping 通 ES
uv run python -c "
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
os.chdir(Path('.').resolve())
from conf.settings import get_settings
from es_store.client import elasticsearch_client
get_settings.cache_clear()
s = get_settings()
c = elasticsearch_client(s)
print('ES_URL=', s.es_url)
print('ES_INDEX=', s.es_index)
print('ping=', c.ping())
"
```

**期望**：`ping=True`。若为 `False`，先排查网络、端口、认证，勿继续大批量入库。

---

## 2. 本地 Markdown 入库：`scripts/rag_ingest.py`

### 2.1 步骤 1：干跑（不切分向量、不写 ES）

```bash
uv run python scripts/rag_ingest.py --dry-run
```

**验证**：终端打印块数；若为 0，检查 `--data-dir` 或默认 `data/` 下是否有 `.md`。

### 2.2 步骤 2：全量替换（推荐，默认删索引重建）

```bash
uv run python scripts/rag_ingest.py --recreate
# 等价于默认
uv run python scripts/rag_ingest.py
```

含义：`EsChunkStore.ensure_index(recreate=True)` → 若索引已存在则 **先 `indices.delete` 再 `indices.create`**，再 bulk。**索引内不会残留历史 chunk**。

**入库后验证**（见 §4）：

- `count` 应等于本次脚本打印的「块数」；
- 可选 `--smoke-query` 做 kNN 抽检。

### 2.3 步骤 3：仅指定文件或目录

```bash
uv run python scripts/rag_ingest.py --files data/md4/民法典.md --recreate
uv run python scripts/rag_ingest.py --data-dir data/md4 --recreate
```

**注意**：`--recreate` 会删掉**整个** `ES_INDEX` 索引；若你只想更新部分文件且不想动其它已入库文件，**不要**用全索引 recreate，应使用 §5 的「先删范围再写入」策略。

---

## 3. OSS 入库：`scripts/ingest_oss_md_to_es.py`

### 3.1 步骤 1：干跑（列举 OSS key，不下载）

```bash
uv run python scripts/ingest_oss_md_to_es.py --dry-run
```

**验证**：终端列出将处理的 `.md` object key；检查桶名、前缀（默认 `rag-law` + `md3/`）是否符合预期。

### 3.2 步骤 2：全量下载 + 切分 + 向量 + 写入（默认删索引重建）

```bash
uv run python scripts/ingest_oss_md_to_es.py --recreate
```

下载目录默认为 `data/md_minerU`；写入字段含 `source_oss_url`。

### 3.3 步骤 3：限制条数（调试）

```bash
uv run python scripts/ingest_oss_md_to_es.py --limit 2 --recreate
```

---

## 4. 入库后必做：Elasticsearch 验证（推荐命令）

以下在**项目根**执行，使用与应用相同的 `Settings` 与客户端。将输出与脚本日志中的「块数」「成功条数」对照。

### 4.1 文档总数 `count`

```bash
uv run python -c "
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
os.chdir(Path('.').resolve())
from conf.settings import get_settings
from es_store.client import elasticsearch_client
get_settings.cache_clear()
s = get_settings()
c = elasticsearch_client(s)
r = c.count(index=s.es_index)
print(json.dumps({'index': s.es_index, 'count': r['count']}, ensure_ascii=False, indent=2))
"
```

**期望（使用 `--recreate` 全量入库时）**：`count` 等于本次入库 chunk 总数（脚本若校验通过会打印一致）。

### 4.2 抽样查看 `_source` 字段（含 `source_oss_url` / `source_sha256`）

```bash
uv run python -c "
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
os.chdir(Path('.').resolve())
from conf.settings import get_settings
from es_store.client import elasticsearch_client
get_settings.cache_clear()
s = get_settings()
c = elasticsearch_client(s)
r = c.search(index=s.es_index, size=3, query={'match_all': {}})
for h in r['hits']['hits']:
    src = h['_source']
    print('_id=', h['_id'])
    print('  source_file=', src.get('source_file'), 'chunk_index=', src.get('chunk_index'))
    print('  source_path=', (src.get('source_path') or '')[:120])
    print('  source_oss_url=', (src.get('source_oss_url') or '')[:120])
    print('---')
"
```

### 4.3 使用 Kibana / Dev Tools（可选）

在 Dev Tools 中（将 `INDEX` 换成你的 `ES_INDEX`）：

```http
GET INDEX/_count

GET INDEX/_search
{
  "size": 1,
  "query": { "match_all": {} }
}
```

---

## 5. 不删除重建索引时，如何「平稳替换」并避免残留

「平稳」通常指：**不执行 `indices.delete`**（避免短暂全索引不可用或需重建 mapping），但仍要让索引内容与本次语料一致。

### 5.1 风险说明（`--no-recreate`）

```bash
uv run python scripts/rag_ingest.py --no-recreate
```

此时 **只保证「写入的 `_id` 被覆盖」**，不保证删除「多出来的旧 `_id`」。

**若必须 `--no-recreate`**，推荐流程：

1. **明确本次入库覆盖的范围**（例如：仅 `data/md_minerU/` 下文件、或 OSS 某批 key 对应的 `source_file` 列表）。
2. **入库前**对该范围执行 **`delete_by_query`**，删除这些来源在 ES 中的旧文档；再执行 **`--no-recreate`** 入库。  
   - 若范围是「整个索引应只有这批数据」，更简单的是仍使用 **`--recreate`**（§2.2 / §3.2）。

### 5.2 示例：按 `source_path` 前缀删除后再写入（OSS 下载文件）

假设本次 OSS 下载文件均落在 `data/md_minerU/`，且 `source_path` 形如 `data/md_minerU/xxx.md`：

```bash
uv run python -c "
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
os.chdir(Path('.').resolve())
from conf.settings import get_settings
from es_store.client import elasticsearch_client
get_settings.cache_clear()
s = get_settings()
c = elasticsearch_client(s)
prefix = 'data/md_minerU/'
body = {
  'query': {
    'prefix': { 'source_path': prefix }
  }
}
r = c.delete_by_query(index=s.es_index, body=body, refresh=True, conflicts='proceed')
print('deleted=', r.get('deleted'), 'version_conflicts=', r.get('version_conflicts'), 'failures=', r.get('failures'))
"
```

**然后再**执行：

```bash
uv run python scripts/ingest_oss_md_to_es.py --no-recreate
```

**验证**：

- 再跑 §4.1，`count` 应等于本次 chunk 数；
- 对 `source_path` 前缀做 `search` + `size: 0` + `track_total_hits`，确认无意外多余文档。

**注意**：`prefix` 查询依赖 mapping 中 `source_path` 为 `keyword`（当前为 keyword）。若前缀与其它业务数据重叠，应改用更精确条件（如 `terms` `source_file`）。

### 5.3 示例：按 `source_file` 列表删除（本地若干文件重跑）

若你明确要替换的文件名为 `A.md`、`B.md`：

```bash
uv run python -c "
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
os.chdir(Path('.').resolve())
from conf.settings import get_settings
from es_store.client import elasticsearch_client
get_settings.cache_clear()
s = get_settings()
c = elasticsearch_client(s)
files = ['A.md', 'B.md']
body = { 'query': { 'terms': { 'source_file': files } } }
r = c.delete_by_query(index=s.es_index, body=body, refresh=True, conflicts='proceed')
print('deleted=', r.get('deleted'), r)
"
```

然后再 `rag_ingest --files ... --no-recreate`。

### 5.4 如何自检「是否还有旧 chunk」

在**已知本次应出现的 `source_file` 集合** $S$ 的前提下：

1. **按 `terms` 查询** `source_file` 在 $S$ 内的文档数，是否等于本次入库脚本输出的块数。
2. **全局 `count`**：若本次为**全量**替换且索引内**只应有**这批数据，则 `count` 应等于块数；若 `count` 大于预期，说明存在未删除的其它 `source_file` 或更高 `chunk_index` 残留。
3. 对单个 `source_file` 查 **最大 `chunk_index`**（需 `search` + `sort` 或聚合）；与本次切分该文件的理论块数比对（脚本日志或 `--dry-run`）。

示例：查看某文件最大 chunk 序号：

```bash
uv run python -c "
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
os.chdir(Path('.').resolve())
from conf.settings import get_settings
from es_store.client import elasticsearch_client
get_settings.cache_clear()
s = get_settings()
c = elasticsearch_client(s)
sf = '你的文件名.md'
r = c.search(
  index=s.es_index,
  size=1,
  query={'term': {'source_file': sf}},
  sort=[{'chunk_index': 'desc'}],
)
hits = r['hits']['hits']
print('max_chunk_index=', hits[0]['_source'].get('chunk_index') if hits else None)
"
```

若该文件本次只应产生 50 块（0–49），而 `max_chunk_index` 仍为 99，则说明 **`--no-recreate` 且未先删** 导致高序号残留。

---

## 5.5 chunk 版本号 `CHUNK_VERSION`（可选）

- 环境变量 **`CHUNK_VERSION`**（如 `1.1.7`）会写入每条 chunk 的 **`chunk_version`** 字段（见 `src/conf/settings.py`、`scripts/rag_ingest.py`、`scripts/ingest_oss_md_to_es.py`）。
- 新数据 **bulk 完成并已 refresh** 之后，可调用 **`es_store.version_cleanup.delete_chunks_not_matching_version`**，删除 `chunk_version` **不等于**当前版本的文档（含**无该字段**的历史数据）。
- 交互式分步验证见 **[c05_ingest_es_runbook.ipynb](c05_ingest_es_runbook.ipynb)**。

---

## 6. 方案对照表（运维选型）

| 目标 | 推荐做法 | 残留风险 |
| --- | --- | --- |
| 整索引只要本次全量数据，可接受删索引 | `rag_ingest` / `ingest_oss_md_to_es` **默认 `--recreate`** | **无**（索引级清空） |
| 不能删索引，但可接受先删文档 | 先 **`delete_by_query`**（范围精确），再 **`--no-recreate`** 入库 | 低（依赖查询条件是否覆盖所有应删文档） |
| 不删索引，用版本号清掉非当前批次 | bulk 写入 **`chunk_version`**，再 **`delete_chunks_not_matching_version`** | 低（须先写完新数据再删；见 §5.5） |
| 不能删索引、也不能先删文档 | 仅用 `--no-recreate` 覆盖写入 | **高**（块数减少或换名时旧 `_id` 残留） |
| 生产级零停机 | 需 **新索引 + 别名切换** 或 **reindex** 等，超出本 MVP 脚本范围 | 需单独设计 |

---

## 7. 执行顺序小结（可复制）

**标准全量替换（最省心、易验证）**

1. §1.2 确认 `ping=True`  
2. `rag_ingest` 或 `ingest_oss_md_to_es` **带 `--recreate`**（默认即 recreate）  
3. §4.1 `count` 与脚本块数一致  
4. §4.2 抽样检查字段  

**限定范围、不删索引**

1. §5.2 或 §5.3 **delete_by_query**（与业务范围一致）  
2. 同一范围 **`--no-recreate`** 入库  
3. §5.4 + §4.1 验证无多余文档、序号合理  

---

## 8. 与计划文档的对应关系

| 计划章节 | 说明 |
| --- | --- |
| [v1.0.4-ingest-plan.md §12](../doc/plan/v1.0.4-ingest-plan.md) | OSS 默认桶/前缀、`source_oss_url`、流水线 |
| [v1.0.3-es-store-plan.md](../doc/plan/v1.0.3-es-store-plan.md) | chunk 字段与 mapping |

若本文与代码行为不一致，以代码与 `doc/plan` 为准，并建议更新本节。
