#!/usr/bin/env bash
# 启动 QA WebUI（BGE + LLM 可选依赖），并可选择同时启动 Filebeat 采集 logs/monitor.log。
#
# Filebeat 说明：
#   - 本仓库提供默认配置：filebeat/filebeat.yml（读取 logs/monitor.log，输出 rag-law-monitor）。
#   - 仍需在本机安装 filebeat 二进制。
#
# 用法：
#   ./scripts/start_qa_webui.sh
#   START_FILEBEAT=1 ./scripts/start_qa_webui.sh
#   START_FILEBEAT=0 ./scripts/start_qa_webui.sh
#   START_FILEBEAT=1 FILEBEAT_CONFIG="$HOME/filebeat-rag-law.yml" ./scripts/start_qa_webui.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[start_qa_webui] project root: $ROOT"

DEFAULT_FILEBEAT_CONFIG="$ROOT/filebeat/filebeat.yml"
FILEBEAT_CONFIG="${FILEBEAT_CONFIG:-$DEFAULT_FILEBEAT_CONFIG}"
export PROJECT_ROOT="$ROOT"

if [[ "${START_FILEBEAT:-1}" == "1" ]]; then
  if ! command -v filebeat >/dev/null 2>&1; then
    echo "[start_qa_webui] 未找到 filebeat 命令，请先安装 Filebeat。" >&2
    exit 1
  fi
  if [[ ! -f "${FILEBEAT_CONFIG}" ]]; then
    echo "[start_qa_webui] 未找到 filebeat 配置: ${FILEBEAT_CONFIG}" >&2
    exit 1
  fi
  echo "[start_qa_webui] 校验 Filebeat 配置: ${FILEBEAT_CONFIG}"
  if ! filebeat test config --strict.perms=false -c "${FILEBEAT_CONFIG}" >/dev/null; then
    echo "[start_qa_webui] Filebeat 配置校验失败，终止启动。" >&2
    exit 1
  fi
  echo "[start_qa_webui] 启动 Filebeat: filebeat -e --strict.perms=false -c ${FILEBEAT_CONFIG}"
  filebeat -e --strict.perms=false -c "${FILEBEAT_CONFIG}" &
  FILEBEAT_PID=$!
  sleep 1
  if ! kill -0 "${FILEBEAT_PID}" 2>/dev/null; then
    echo "[start_qa_webui] Filebeat 启动失败，终止启动 WebUI。" >&2
    exit 1
  fi
  echo "[start_qa_webui] Filebeat 已启动 (pid=${FILEBEAT_PID})"
  trap 'kill "${FILEBEAT_PID}" 2>/dev/null || true' EXIT
else
  echo "[start_qa_webui] 已跳过 Filebeat（START_FILEBEAT=0）。手动示例："
  echo "  filebeat -e --strict.perms=false -c ${DEFAULT_FILEBEAT_CONFIG}"
  echo "或: START_FILEBEAT=1 FILEBEAT_CONFIG=/path/to/filebeat.yml $0"
fi

echo "[start_qa_webui] uv sync --extra embedding --extra llm"
uv sync --extra embedding --extra llm --extra segmentation

echo "[start_qa_webui] uvicorn qa.webui.app:app --host 0.0.0.0 --port 8766"
exec uv run uvicorn qa.webui.app:app --host 0.0.0.0 --port 8766
