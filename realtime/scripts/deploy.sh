#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REALTIME_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${REALTIME_DIR}/.." && pwd)"
# shellcheck source=../../scripts/pi-deploy-lib.sh
source "${REPO_ROOT}/scripts/pi-deploy-lib.sh"

PI_HOST=""
PI_USER=""
PI_PORT="22"

usage() {
  cat <<'EOF'
Usage: ./realtime/scripts/deploy.sh --host <pi_host> --user <pi_user> [--port 22]

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

require_command ssh scp tar python3

DEPLOY_HOME="/home/${PI_USER}"
REALTIME_REMOTE_DIR="${DEPLOY_HOME}/voice-assistant-realtime/realtime"
DATA_REMOTE_DIR="${DEPLOY_HOME}/voice-assistant-realtime/data"
OBSOLETE_REMOTE_PATHS=(
  "${REALTIME_REMOTE_DIR}/ambient_soft_loop.wav"
  "${REALTIME_REMOTE_DIR}/end_cue.wav"
  "${REALTIME_REMOTE_DIR}/lofi_soft_loop.wav"
  "${REALTIME_REMOTE_DIR}/ready_cue.wav"
  "${REALTIME_REMOTE_DIR}/ready_end_reverse.wav"
  "${REALTIME_REMOTE_DIR}/ready_mellow_drop.wav"
  "${REALTIME_REMOTE_DIR}/ready_soft_glow.wav"
  "${REALTIME_REMOTE_DIR}/ready_warm_double.wav"
  "${REALTIME_REMOTE_DIR}/search_wait_loop.wav"
  "${REALTIME_REMOTE_DIR}/soft_piano_loop.wav"
  "${REALTIME_REMOTE_DIR}/wake_chime.wav"
  "${REALTIME_REMOTE_DIR}/wake_clear_rise.wav"
  "${REALTIME_REMOTE_DIR}/wake_gentle_double.wav"
  "${REALTIME_REMOTE_DIR}/wake_soft_bell.wav"
  "${REALTIME_REMOTE_DIR}/snowman-realtime.service"
  "${REALTIME_REMOTE_DIR}/snowman-realtime.service.in"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-healthcheck.service"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-healthcheck.service.in"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-healthcheck.timer"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-window-start.service"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-window-start.timer"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-window-stop.service"
  "${REALTIME_REMOTE_DIR}/snowman-realtime-window-stop.timer"
  "${REALTIME_REMOTE_DIR}/test_location_context.py"
  "${REALTIME_REMOTE_DIR}/test_output_gain.py"
  "${REALTIME_REMOTE_DIR}/test_voicehat_button.py"
  "${REALTIME_REMOTE_DIR}/check_realtime_health.sh"
  "${REALTIME_REMOTE_DIR}/deploy.sh"
  "${REALTIME_REMOTE_DIR}/main.py"
  "${REALTIME_REMOTE_DIR}/probe_realtime_connect.py"
  "${REALTIME_REMOTE_DIR}/start_realtime.sh"
  "${REALTIME_REMOTE_DIR}/within_runtime_window.sh"
  "${REALTIME_REMOTE_DIR}/scripts/main.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/__init__.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/base.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/local_time.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/profile_memory_get.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/profile_memory_update.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/registry.py"
  "${REALTIME_REMOTE_DIR}/snowman_realtime/tools/web_search.py"
)

log "Deploying realtime to ${PI_USER}@${PI_HOST}:${REALTIME_REMOTE_DIR}"

run_remote "mkdir -p $(quote_remote "${REALTIME_REMOTE_DIR}") $(quote_remote "${DATA_REMOTE_DIR}")"
copy_dir_contents_to_remote "${REALTIME_DIR}" "${REALTIME_REMOTE_DIR}"
run_remote "chmod 755 \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/start_realtime.sh") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/start_config_ui.sh") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/apply_config.sh") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/check_legacy_config_match.py") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/check_realtime_health.sh") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/within_runtime_window.sh") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/probe_realtime_connect.py") \
  $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/migrate_legacy_config.py")"
install_rendered_template_to_remote "${REALTIME_DIR}/systemd/snowman-realtime.service.in" "0644" "/etc/systemd/system/snowman-realtime.service"
install_rendered_template_to_remote "${REALTIME_DIR}/systemd/snowman-realtime-healthcheck.service.in" "0644" "/etc/systemd/system/snowman-realtime-healthcheck.service"
install_file_to_remote "${REALTIME_DIR}/systemd/snowman-realtime-healthcheck.timer" "0644" "/etc/systemd/system/snowman-realtime-healthcheck.timer"
install_rendered_template_to_remote "${REALTIME_DIR}/systemd/snowman-config-ui.service.in" "0644" "/etc/systemd/system/snowman-config-ui.service"
install_rendered_template_to_remote "${REALTIME_DIR}/systemd/snowman-config-ui.sudoers.in" "0440" "/etc/sudoers.d/snowman-config-ui"

cleanup_command="rm -f"
for obsolete_path in "${OBSOLETE_REMOTE_PATHS[@]}"; do
  cleanup_command+=" $(quote_remote "${obsolete_path}")"
done
run_remote "${cleanup_command}"
run_remote "find $(quote_remote "${REALTIME_REMOTE_DIR}") -name '._*' -delete -o -name '.DS_Store' -delete"

run_remote "python3 -m venv $(quote_remote "${REALTIME_REMOTE_DIR}/venv")"
run_remote "$(quote_remote "${REALTIME_REMOTE_DIR}/venv/bin/pip") install --upgrade pip wheel"
run_remote "$(quote_remote "${REALTIME_REMOTE_DIR}/venv/bin/pip") install -r $(quote_remote "${REALTIME_REMOTE_DIR}/requirements.txt")"
run_remote "$(quote_remote "${REALTIME_REMOTE_DIR}/venv/bin/python") $(quote_remote "${REALTIME_REMOTE_DIR}/scripts/migrate_legacy_config.py") --data-dir $(quote_remote "${DATA_REMOTE_DIR}") --legacy-env-file $(quote_remote "${REALTIME_REMOTE_DIR}/.env")"

run_remote "sudo systemctl daemon-reload"
run_remote "sudo systemctl disable --now snowman-realtime-window-start.timer snowman-realtime-window-stop.timer >/dev/null 2>&1 || true"
run_remote "sudo systemctl enable snowman-realtime.service"
run_remote "sudo systemctl enable snowman-realtime-healthcheck.timer"
run_remote "sudo systemctl enable snowman-config-ui.service"
run_remote "sudo systemctl restart snowman-config-ui.service"
run_remote "sudo systemctl restart snowman-realtime.service"

show_remote_status "snowman-realtime.service"

log ""
log "Realtime deploy complete."
log "Logs: ssh ${PI_USER}@${PI_HOST} 'tail -f ${REALTIME_REMOTE_DIR}/realtime.log'"
