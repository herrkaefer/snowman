#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_TIMER_PATH="${START_TIMER_PATH:-/etc/systemd/system/snowman-realtime-window-start.timer}"
STOP_TIMER_PATH="${STOP_TIMER_PATH:-/etc/systemd/system/snowman-realtime-window-stop.timer}"

if [[ ! -f "${START_TIMER_PATH}" ]]; then
  START_TIMER_PATH="${SCRIPT_DIR}/snowman-realtime-window-start.timer"
fi

if [[ ! -f "${STOP_TIMER_PATH}" ]]; then
  STOP_TIMER_PATH="${SCRIPT_DIR}/snowman-realtime-window-stop.timer"
fi

extract_time() {
  local timer_path="$1"
  sed -n 's/^OnCalendar=.* \([0-9][0-9]:[0-9][0-9]\):[0-9][0-9]$/\1/p' "${timer_path}" | head -n 1
}

window_start="$(extract_time "${START_TIMER_PATH}")"
window_stop="$(extract_time "${STOP_TIMER_PATH}")"
now_local="$(date +%H:%M)"

if [[ -z "${window_start}" || -z "${window_stop}" ]]; then
  echo "Runtime window misconfigured: could not parse start/stop from timer files" >&2
  exit 1
fi

if [[ "${window_start}" == "${window_stop}" ]]; then
  echo "Runtime window misconfigured: start and stop are both ${window_start}" >&2
  exit 1
fi

if [[ "${window_start}" < "${window_stop}" ]]; then
  if [[ "${now_local}" > "${window_start}" && "${now_local}" < "${window_stop}" ]] || [[ "${now_local}" == "${window_start}" ]]; then
    exit 0
  fi
else
  if [[ "${now_local}" > "${window_start}" || "${now_local}" < "${window_stop}" ]] || [[ "${now_local}" == "${window_start}" ]]; then
    exit 0
  fi
fi

echo "Outside runtime window: now=${now_local}, allowed=${window_start}-${window_stop}" >&2
exit 1
