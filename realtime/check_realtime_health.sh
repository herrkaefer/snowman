#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${APP_DIR:-${SCRIPT_DIR}}"
SERVICE_NAME="${SERVICE_NAME:-snowman-realtime.service}"
LOG_PATH="${LOG_PATH:-${APP_DIR}/realtime.log}"
MAX_HEARTBEAT_AGE_SECONDS="${MAX_HEARTBEAT_AGE_SECONDS:-300}"
MAIN_PATTERN="${MAIN_PATTERN:-${APP_DIR}/venv/bin/python3 -u ${APP_DIR}/main.py}"
WINDOW_CHECK_SCRIPT="${WINDOW_CHECK_SCRIPT:-${APP_DIR}/within_runtime_window.sh}"

if ! "${WINDOW_CHECK_SCRIPT}"; then
  echo "Healthcheck: outside runtime window; skipping"
  exit 0
fi

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "Healthcheck: ${SERVICE_NAME} inactive; restarting"
  systemctl restart "${SERVICE_NAME}"
  exit 0
fi

process_count="$(pgrep -fc "${MAIN_PATTERN}" || true)"
if [[ "${process_count}" != "1" ]]; then
  echo "Healthcheck: expected 1 realtime process, found ${process_count}; restarting"
  systemctl restart "${SERVICE_NAME}"
  exit 0
fi

service_started_us="$(systemctl show "${SERVICE_NAME}" -p ActiveEnterTimestampMonotonic --value)"
uptime_seconds="${UPTIME_SECONDS:-$(cut -d. -f1 /proc/uptime)}"
service_age_seconds="$(( uptime_seconds - service_started_us / 1000000 ))"

heartbeat_status="$(
python3 - "${LOG_PATH}" "${MAX_HEARTBEAT_AGE_SECONDS}" <<'PY'
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
max_age = float(sys.argv[2])
if not log_path.exists():
    print("missing_log")
    raise SystemExit(0)

last_ts: dt.datetime | None = None
for line in log_path.read_text(errors="ignore").splitlines():
    if "Health heartbeat:" not in line:
        continue
    try:
        last_ts = dt.datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        continue

if last_ts is None:
    print("missing_heartbeat")
    raise SystemExit(0)

age = (dt.datetime.now() - last_ts).total_seconds()
if age > max_age:
    print(f"stale:{age:.1f}")
else:
    print(f"ok:{age:.1f}")
PY
)"

case "${heartbeat_status}" in
  ok:*)
    echo "Healthcheck: ${heartbeat_status}"
    ;;
  missing_heartbeat)
    if (( service_age_seconds < MAX_HEARTBEAT_AGE_SECONDS )); then
      echo "Healthcheck: ${heartbeat_status}, service_age=${service_age_seconds}s; allowing startup window"
      exit 0
    fi
    echo "Healthcheck: ${heartbeat_status}, service_age=${service_age_seconds}s; restarting ${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    ;;
  *)
    echo "Healthcheck: ${heartbeat_status}; restarting ${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    ;;
esac
