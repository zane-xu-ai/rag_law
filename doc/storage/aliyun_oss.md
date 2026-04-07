# 阿里云 OSS 到 RAG 入库（bucket: `rag-law`）操作说明

本文目标：从 OSS 读取对象文件，落地到本地目录后执行“切片 + 向量化 + 入 ES”。

参考：
- [OSS Python SDK V2：配置客户端](https://help.aliyun.com/zh/oss/developer-reference/configure-client-using-oss-sdk-for-python-v2)
- 项目脚本与封装：
  - [`src/utils/oss_aliyun/`](../../src/utils/oss_aliyun)
  - [`scripts/rag_ingest.py`](../../scripts/rag_ingest.py)

---

## 1. 前置配置

### 1.1 凭证与地域

在 `.env` 或 shell 环境中配置：

```bash
OSS_ACCESS_KEY_ID=...
OSS_ACCESS_KEY_SECRET=...
OSS_REGION=cn-hangzhou
# 可选
# OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
```

说明：
- OSS SDK V2 推荐读取 `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`。
- 本项目兼容旧名 `accessKeyId` / `accessKeySecret`，但建议统一改为官方变量名。
- 单独运行 `python -m utils.oss_aliyun.cli` 时，[`build_client_from_env`](../../src/utils/oss_aliyun/client.py) 会尝试加载**仓库根目录**下的 `.env`（`load_dotenv(..., override=False)`，不覆盖已在 shell 里 export 的变量）。pytest 运行中跳过加载，与 `conf.settings` 行为一致。

### 1.2 依赖与 RAG 配置

```bash
uv sync --extra oss --extra embedding
```

并确保以下变量可用：
- `BGE_M3_PATH`
- `ES_HOST` / `ES_PORT` / `ES_INDEX`

---

## 2. OSS 文件读取（下载到本地）

当前 CLI 提供 `put/get/head/delete`（见 [`src/utils/oss_aliyun/cli.py`](../../src/utils/oss_aliyun/cli.py)）。

示例：从 bucket `rag-law` 下载对象到本地：

```bash
python -m utils.oss_aliyun.cli get \
  --bucket rag-law \
  --key docs/民法典.md \
  --out data/inbox/民法典.md
```

可选元数据检查：

```bash
python -m utils.oss_aliyun.cli head \
  --bucket rag-law \
  --key docs/民法典.md
```

备注：若你需要批量下载，建议后续补一个 `list` 子命令（当前未实现）。

---

## 3. 切片、向量化并写入 ES

### 3.1 先 dry-run 看块数

```bash
uv run python scripts/rag_ingest.py \
  --files data/inbox/民法典.md \
  --dry-run
```

### 3.2 正式入库（增量）

```bash
uv run python scripts/rag_ingest.py \
  --files data/inbox/民法典.md \
  --no-recreate \
  --smoke-query "合同"
```

说明：
- `--files`：只处理指定文件。
- `--no-recreate`：增量写入，不删除现有索引（生产常用）。
- 默认 `--recreate` 会删索引重建，谨慎使用。

---

## 4. 常见风险与建议

1. 密钥泄漏：禁止把 AK/SK 提交到 Git 或打印日志。
2. Region/Endpoint 不匹配：优先只配 `OSS_REGION`，必要时再显式 `OSS_ENDPOINT`。
3. 权限过大：优先 RAM 子用户最小权限策略。
4. 同名文件覆盖：ES 文档 `_id` 与 `source_file:chunk_index` 相关，重复入库同名文件会覆盖对应块（属于预期行为）。

---

## 5. 最小权限建议（读取 + 可选写入）

若仅从 OSS 读取对象用于入库，策略至少包含：
- `oss:GetObject`
- `oss:ListObjects` / `oss:ListObjectsV2`（需要列举时）

若需要回写 OSS（上传/删除），再增加：
- `oss:PutObject`
- `oss:DeleteObject`


