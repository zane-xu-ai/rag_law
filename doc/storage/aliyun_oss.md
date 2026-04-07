# 阿里云 OSS：Python SDK 客户端与凭证配置计划（不改业务代码）

本文只给出落地计划，目标是让你在本机（darwin + zsh）完成：

1. 配置 OSS 访问凭证（环境变量）。
2. 用 OSS Python SDK V2 初始化客户端。
3. 做一次最小可用连通性验证（例如 put/get 或列举 Bucket 信息）。

---

## 1. 依据与范围

- 参考文档：
  - [OSS Python SDK V2：配置客户端](https://help.aliyun.com/zh/oss/developer-reference/configure-client-using-oss-sdk-for-python-v2)
  - [OSS Python SDK V1 快速入门（仅作背景）](https://help.aliyun.com/zh/oss/developer-reference/getting-started-with-oss-sdk-for-python)
- 本文以 **SDK V2** 为主，使用 `alibabacloud-oss-v2`。
- 凭证方式采用文档推荐的 **RAM 用户 AccessKey + 环境变量**（`OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`）。

---

## 2. 计划步骤

### 步骤 A：准备 RAM 账号与权限

1. 在 RAM 控制台创建用于程序访问 OSS 的 RAM 用户。
2. 为该用户授予最小必要权限（文档示例为 `AliyunOSSFullAccess`，生产建议改最小权限策略）。
3. 保存该用户的 `AccessKeyId` 与 `AccessKeySecret`。

### 步骤 B：本机配置凭证（macOS + zsh）

1. 将凭证写入 `~/.zshrc`：
  - `export OSS_ACCESS_KEY_ID='...'`
  - `export OSS_ACCESS_KEY_SECRET='...'`
2. 执行 `source ~/.zshrc` 使其生效。
3. 通过 `echo $OSS_ACCESS_KEY_ID` 等命令确认环境变量存在。

说明：后续 SDK 通过 `EnvironmentVariableCredentialsProvider` 读取这两个变量，不在代码里硬编码密钥。

### 步骤 C：安装并初始化 OSS Python SDK V2

1. 安装依赖：`pip install alibabacloud-oss-v2`。
2. 在脚本中 `import alibabacloud_oss_v2 as oss`。
3. 初始化关键点：
  - `credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()`
  - `cfg = oss.config.load_default()`
  - `cfg.credentials_provider = credentials_provider`
  - 设置 `cfg.region = '<region-id>'`（必填）
  - 可选设置 `cfg.endpoint = '<endpoint>'`（如需显式指定）
  - `client = oss.Client(cfg)`

### 步骤 D：最小可用验证

建议在独立脚本中做一次最小验证（不改现有业务链路）：

1. 使用一个测试 Bucket 与对象 Key 执行 `put_object`。
2. 校验返回 `status_code`、`request_id`、`etag`。
3. 可选再做一次读取或删除，形成闭环验证。

### 步骤 E：与本项目集成前的检查清单

1. 明确 Bucket 所在 Region，确保 `region/endpoint` 与 Bucket 一致。
2. 明确对象命名规则（例如按日期或文档类型分前缀）。
3. 明确错误处理策略：鉴权失败、Endpoint 配置错误、网络超时、限流重试。
4. 明确日志脱敏要求：禁止打印 AK/SK。

---

## 3. 产出物计划

本阶段建议产出（后续再实现）：

1. `scripts/` 下一个 OSS 连通性验证脚本（仅测试用途）。
2. `src/` 下一个轻量 OSS 客户端封装模块（统一读取环境变量与构造客户端）。
3. 一页运维说明：如何在本地、CI、服务器注入 `OSS_ACCESS_KEY_ID/SECRET`。

---

## 4. 风险与规避

1. **风险：密钥泄漏**
  - 规避：只用环境变量或密钥管理服务，不写入仓库，不进日志。
2. **风险：Region/Endpoint 不匹配导致请求失败**
  - 规避：优先只配 `region`，必要时再显式 `endpoint`，并使用官方地域表核对。
3. **风险：权限过大**
  - 规避：开发期可快速验证，生产改为最小权限 RAM 策略。

---

## 5. 后续实施建议（可选）

当你确认该计划后，再进入实现阶段：

1. 先做独立脚本验证客户端可用；
2. 再封装到项目模块；
3. 最后接入主流程并补测试。

