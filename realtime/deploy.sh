#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../scripts/pi-deploy-lib.sh
source "${REPO_ROOT}/scripts/pi-deploy-lib.sh"

PI_HOST=""
PI_USER=""
PI_PORT="22"
ENV_FILE="${SCRIPT_DIR}/.env"

usage() {
  cat <<'EOF'
Usage: ./realtime/deploy.sh --host <pi_host> --user <pi_user> [--port 22] [--env-file realtime/.env]

Deploys the realtime app to /home/<user>/voice-assistant-realtime/realtime,
installs parameterized systemd units, enables the main service and healthcheck
timer, and restarts the service.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      PI_HOST="${2:-}"
      shift 2
      ;;
    --user)
      PI_USER="${2:-}"
      shift 2
      ;;
    --port)
      PI_PORT="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ -n "${PI_HOST}" ]] || fail "--host is required"
[[ -n "${PI_USER}" ]] || fail "--user is required"
[[ -f "${ENV_FILE}" ]] || fail "Env file not found: ${ENV_FILE}"

require_command ssh scp tar python3

DEPLOY_HOME="/home/${PI_USER}"
REALTIME_REMOTE_DIR="${DEPLOY_HOME}/voice-assistant-realtime/realtime"

log "Deploying realtime to ${PI_USER}@${PI_HOST}:${REALTIME_REMOTE_DIR}"

run_remote "mkdir -p $(quote_remote "${REALTIME_REMOTE_DIR}")"
copy_dir_contents_to_remote "${SCRIPT_DIR}" "${REALTIME_REMOTE_DIR}"
copy_file_to_remote "${ENV_FILE}" "${REALTIME_REMOTE_DIR}/.env"
install_rendered_template_to_remote "${SCRIPT_DIR}/snowman-realtime.service.in" "0644" "/etc/systemd/system/snowman-realtime.service"
install_rendered_template_to_remote "${SCRIPT_DIR}/snowman-realtime-healthcheck.service.in" "0644" "/etc/systemd/system/snowman-realtime-healthcheck.service"
install_file_to_remote "${SCRIPT_DIR}/snowman-realtime-healthcheck.timer" "0644" "/etc/systemd/system/snowman-realtime-healthcheck.timer"

run_remote "python3 -m venv $(quote_remote "${REALTIME_REMOTE_DIR}/venv")"
run_remote "$(quote_remote "${REALTIME_REMOTE_DIR}/venv/bin/pip") install --upgrade pip wheel"
run_remote "$(quote_remote "${REALTIME_REMOTE_DIR}/venv/bin/pip") install -r $(quote_remote "${REALTIME_REMOTE_DIR}/requirements.txt")"

run_remote "sudo systemctl daemon-reload"
run_remote "sudo systemctl disable --now snowman-realtime-window-start.timer snowman-realtime-window-stop.timer >/dev/null 2>&1 || true"
run_remote "sudo systemctl enable snowman-realtime.service"
run_remote "sudo systemctl enable snowman-realtime-healthcheck.timer"
run_remote "sudo systemctl restart snowman-realtime.service"

show_remote_status "snowman-realtime.service"

log ""
log "Realtime deploy complete."
log "Logs: ssh ${PI_USER}@${PI_HOST} 'tail -f ${REALTIME_REMOTE_DIR}/realtime.log'"
