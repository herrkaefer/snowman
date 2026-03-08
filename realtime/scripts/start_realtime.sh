#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${APP_DIR}/venv/bin/python3"
MAIN_MODULE="snowman_realtime"
PATTERN="${APP_DIR}/venv/bin/python3 -u -m ${MAIN_MODULE}"

existing_pids="$(pgrep -f "${PATTERN}" || true)"
if [[ -n "${existing_pids}" ]]; then
  echo "Stopping existing realtime instance(s): ${existing_pids}" >&2
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill "${pid}" 2>/dev/null || true
  done <<< "${existing_pids}"
  sleep 0.5
fi

cd "${APP_DIR}"
exec "${PYTHON_BIN}" -u -m "${MAIN_MODULE}"
