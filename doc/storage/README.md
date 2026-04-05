# 存储与元数据分层（RAG / 多模态扩展）

本文整理「文档、chunk、pdf2json、图片、表格及元数据」在不同系统中的存放方式，以及与 Elasticsearch、关系库、对象存储（OSS / MinIO）的分工。可与 [doc/plan/v1.0.1-chunking-plan.md](../plan/v1.0.1-chunking-plan.md) 中的切分与 `TextChunk` 扩展字段对照阅读。

---

## 1. 先分清三类数据

| 类型 | 典型内容 | 特点 |
| --- | --- | --- |
| **原文与二进制** | PDF 原件、从 PDF 导出的**图片**、体积较大的解析结果文件 | 体积大、按 key 存取，不适合频繁当「行」更新 |
| **结构化业务数据** | 文档 ID、标题、领域、入库批次、权限、解析版本、任务状态 | 强一致、关联查询、事务 |
| **检索单元（chunk）** | 可向量化的文本段 + 向量 + **检索与过滤所需元数据** | 读多、相似度搜索、过滤 |

RAG 中的「chunk」主要指第三类；第一类、第二类由对象存储与关系库分别承接。

---

## 2. 各类内容适合放在哪里

### Elasticsearch（适合）

- 每个 **chunk** 一条文档（MVP 扁平结构即可；后续可父子索引等）。
- 建议包含：
  - **向量**：`dense_vector`
  - **参与检索的文本**：正文、OCR 文本、表格转成的纯文本等
  - **过滤与展示**：`document_id`、`chunk_index`、`page` 或 `page_start` / `page_end`、`modality`（如 `text` / `image` / `table` / `mixed`）、`doc_type`、`domain`
  - **大块非检索字段**：可用 `extra` 存 JSON（页码、bbox、原 JSON 块 id、图片在对象存储中的 **key** 等）
- **原则**：只放检索与排序需要的内容；**不要**在 ES 里塞大体积 base64 图片或整份巨型 JSON。

### MySQL / PostgreSQL（适合）

- **文档级**：例如 `documents` 表：id、标题、来源、领域、`storage_uri`（原件位置）、`mime_type`、解析状态、`parser_version`、创建时间等。
- **可选**：`ingestion_jobs`、权限、用户、多版本解析记录。
- **chunk 是否落 MySQL**：通常 **不以 MySQL 作为 chunk 主存储**（与 ES 重复且难维护）；检索以 **ES 为准**。若有合规/审计要求，可 **ES 为主 + MySQL 存摘要或关联关系**，按业务设计。

### OSS / MinIO / S3 兼容存储（适合）

- **PDF 原件**、导出的**图片**、体积大的 **pdf2json 原始 JSON**、表格导出的 **HTML/CSV 附件** 等。
- 仅存 **URI / bucket / object key**；业务库或 ES 中保存引用，不内嵌整文件。

### 图片与表格

- **图片**：文件在**对象存储**；对应 chunk 在 ES 中：`modality=image`、可选 `caption` / `ocr_text`（用于检索）、`image_uri` 或 `object_key`。
- **表格**：参与检索的文本（纯文本或 Markdown）进 **ES**；若需保留原始 HTML/大 JSON，**大文件放对象存储**，ES 存摘要与链接。

---

## 3. Chunk 元数据示例（与文档、页、类型关联）

建议在每条 chunk 上统一携带（字段名可按实现调整）：

| 字段（概念） | 说明 |
| --- | --- |
| `document_id` | 关联关系库中 `documents.id` 或业务 UUID |
| `page` / `page_range` | PDF 等页码 |
| `modality` | `text` / `image` / `table` / `mixed` 等 |
| `extra`（JSON） | `bbox`、`figure_id`、`source_block_id`、子类型、指向 OSS 的 key 等 |

**pdf2json → 切分**：解析结果可为「页 / 块树」存于对象存储；切分阶段只对需要检索的文本生成 chunk 写入 ES，并在 `extra` 中保留 `json_path` 或 `block_id` 以便回溯。

---

## 4. 「OSS」是一类服务还是一个具体产品？

- **对象存储（Object Storage）** 是一**类**服务：按 bucket + key 存 blob，HTTP API，适合文件与大对象。
- 中文语境里 **「OSS」** 常特指 **阿里云对象存储 OSS**（一个具体产品名称）。
- **Amazon S3**、**Google Cloud Storage**、**Azure Blob**、**MinIO** 等均属同类；**MinIO** 实现 **S3 兼容 API**，常用于自建或本地开发，替代云厂商对象存储的调用方式。

**结论**：口语中的「OSS」多指阿里云产品；严格分类应称「对象存储」，再选定具体厂商或自建方案。

---

## 5. 本地 Docker 启动类 OSS 服务（MinIO）

本地开发一般**不**运行阿里云 OSS 真实服务，而是使用 **MinIO** 模拟 S3 API。

### 5.1 本机已有实例（记录，便于区分）

若你曾在本机为 **Milvus** 等组件启动过 MinIO，可能与「本 RAG 项目单独一套」并存，例如：

| 项目 | 说明（示例） |
| --- | --- |
| 容器名 | `milvus-minio` |
| 镜像 | `minio/minio:RELEASE.2023-03-20T20-16-18Z`（示例，以你机器 `docker ps` 为准） |
| 端口 | 常见为容器内 `9000`；若由 Milvus 的 compose 管理，**宿主机映射端口以 `docker ps` / compose 文件为准** |

**不要**与下面「RAG 专用」实例抢同一宿主机端口；若 9000/9001 已被占用，请为 RAG 使用**其他宿主机端口**（见 5.3）。

### 5.2 用 Dockerfile 还是 Docker Compose？

| 方式 | 说明 |
| --- | --- |
| **Dockerfile** | 用来**构建自定义镜像**（`FROM` + 安装依赖等）。MinIO 直接使用**官方镜像**即可，**一般不需要**为 MinIO 再写 Dockerfile。 |
| **`docker run`** | 一条命令起容器，适合临时试用；端口、卷、环境变量一多就不好维护。 |
| **Docker Compose（推荐）** | 用 YAML **固定镜像版本、端口、卷、环境变量**，可提交到仓库、团队一致、与 Milvus 栈分离；**本仓库推荐用 Compose 单独起一套 RAG 用 MinIO**。 |

结论：**优先用 Docker Compose**；无需为 MinIO 单独写 Dockerfile。

### 5.3 RAG 专用 MinIO：配置与启动（请你自行执行）

仓库内提供示例编排：[docker-compose.minio.example.yml](docker-compose.minio.example.yml)（勿与 Milvus 的 compose 混用同一文件，除非你知道自己在做什么）。

| 配置项 | 示例文件中的约定 |
| --- | --- |
| 容器名 | `rag-law-minio`（与 `milvus-minio` 区分） |
| 宿主机 S3 API | **9002** → 容器 9000 |
| 宿主机控制台 | **9003** → 容器 9001 |
| 默认账号 | `MINIO_ROOT_USER=minioadmin` / `MINIO_ROOT_PASSWORD=minioadmin`（**生产务必修改**） |
| 数据卷 | 命名卷 `rag_law_minio_data`，数据持久在 Docker volume 中 |

**启动步骤（在项目根或复制 yml 的目录下执行）：**

```bash
# 将示例复制到当前目录（或直接用 -f 指定路径）
cp doc/storage/docker-compose.minio.example.yml ./docker-compose.minio.yml

docker compose -f docker-compose.minio.yml up -d
```

查看状态：

```bash
docker ps --filter name=rag-law-minio
docker logs rag-law-minio
```

**应用侧连接：**

| 用途 | 地址 |
| --- | --- |
| S3 兼容 API | `http://127.0.0.1:9002`（或局域网 IP + 9002） |
| Web 控制台 | `http://127.0.0.1:9003`（浏览器创建 bucket、上传文件） |

SDK 中 endpoint 填 `http://127.0.0.1:9002`，使用上述 `minioadmin` / `minioadmin`（或你改后的环境变量），并指定 bucket 名。

**停止与删除（谨慎，会删卷则数据清空）：**

```bash
docker compose -f docker-compose.minio.yml down
# 仅停容器保留卷：down 不加 -v；删卷需加 -v 并确认
```

生产环境若改用阿里云 OSS，通常只更换 endpoint 与凭证，**对象 key + 库内引用** 的数据模型可保持一致。

---

## 6. 小结对照表

| 内容 | 推荐存储 |
| --- | --- |
| Chunk + 向量 + 检索与过滤字段 | **Elasticsearch** |
| 文档目录、权限、解析任务、强一致业务 | **MySQL / PostgreSQL** |
| PDF、图片、大 JSON、表格附件 | **对象存储**（云 OSS / MinIO / S3） |
| 本地开发 | **Docker 运行 MinIO** 即可 |

---

## 7. 相关文档

| 文档 | 说明 |
| --- | --- |
| [doc/plan/v1.0.1-chunking-plan.md](../plan/v1.0.1-chunking-plan.md) | 切分、`TextChunk` 扩展字段与 PDF→JSON 衔接 |
| [doc/plan/v1.0.0-rag-law-mvp-plan.md](../plan/v1.0.0-rag-law-mvp-plan.md) | MVP 总计划与 ES 索引设计要点 |
