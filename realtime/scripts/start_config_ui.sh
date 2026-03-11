#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${APP_DIR}/venv/bin/python3"

cd "${APP_DIR}"
exec "${PYTHON_BIN}" -u -m snowman_realtime.config_ui
