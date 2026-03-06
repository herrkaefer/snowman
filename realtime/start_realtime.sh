#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/venv/bin/python3"
MAIN_PY="${ROOT_DIR}/main.py"
PATTERN="${ROOT_DIR}/venv/bin/python3 -u ${MAIN_PY}"

existing_pids="$(pgrep -f "${PATTERN}" || true)"
if [[ -n "${existing_pids}" ]]; then
  echo "Stopping existing realtime instance(s): ${existing_pids}" >&2
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill "${pid}" 2>/dev/null || true
  done <<< "${existing_pids}"
  sleep 0.5
fi

exec "${PYTHON_BIN}" -u "${MAIN_PY}"
