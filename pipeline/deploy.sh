#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../scripts/pi-deploy-lib.sh
source "${REPO_ROOT}/scripts/pi-deploy-lib.sh"

PI_HOST=""
PI_USER=""
PI_PORT="22"
ENV_FILE="${SCRIPT_DIR}/.env.pi"

usage() {
  cat <<'EOF'
Usage: ./pipeline/deploy.sh --host <pi_host> --user <pi_user> [--port 22] [--env-file pipeline/.env.pi]

Deploys the pipeline app to /home/<user>/voice-assistant, installs the template
systemd unit, refreshes the virtualenv, and restarts the service instance.
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
PIPELINE_REMOTE_DIR="${DEPLOY_HOME}/voice-assistant"
PIPELINE_SERVICE_NAME="voice-assistant@${PI_USER}.service"

log "Deploying pipeline to ${PI_USER}@${PI_HOST}:${PIPELINE_REMOTE_DIR}"

run_remote "mkdir -p $(quote_remote "${PIPELINE_REMOTE_DIR}")"
copy_dir_contents_to_remote "${SCRIPT_DIR}" "${PIPELINE_REMOTE_DIR}"
copy_file_to_remote "${ENV_FILE}" "${PIPELINE_REMOTE_DIR}/.env"
install_file_to_remote "${SCRIPT_DIR}/voice-assistant@.service" "0644" "/etc/systemd/system/voice-assistant@.service"

run_remote "python3 -m venv $(quote_remote "${PIPELINE_REMOTE_DIR}/venv")"
run_remote "$(quote_remote "${PIPELINE_REMOTE_DIR}/venv/bin/pip") install --upgrade pip wheel"
run_remote "$(quote_remote "${PIPELINE_REMOTE_DIR}/venv/bin/pip") install -r $(quote_remote "${PIPELINE_REMOTE_DIR}/requirements.txt")"

run_remote "sudo systemctl daemon-reload"
run_remote "sudo systemctl disable --now voice-assistant.service >/dev/null 2>&1 || true"
run_remote "sudo systemctl enable $(quote_remote "${PIPELINE_SERVICE_NAME}")"
run_remote "sudo systemctl restart $(quote_remote "${PIPELINE_SERVICE_NAME}")"

show_remote_status "${PIPELINE_SERVICE_NAME}"

log ""
log "Pipeline deploy complete."
log "Logs: ssh ${PI_USER}@${PI_HOST} 'sudo journalctl -u ${PIPELINE_SERVICE_NAME} -f'"
