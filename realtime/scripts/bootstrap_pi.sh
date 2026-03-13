#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REALTIME_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_HOME="${SNOWMAN_APP_HOME:-$HOME/voice-assistant-realtime}"
DATA_DIR="${SNOWMAN_DATA_DIR:-${APP_HOME}/data}"
TARGET="realtime"
CONFIG_UI_PORT="${SNOWMAN_CONFIG_UI_PORT:-3010}"
SYSTEMCTL_BIN="$(command -v systemctl)"

usage() {
  cat <<'EOF'
Usage: ./realtime/scripts/bootstrap_pi.sh [--target realtime|pipeline]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "${TARGET}" != "realtime" ]]; then
  echo "pipeline install is not implemented yet" >&2
  exit 1
fi

if [[ "${REALTIME_DIR}" != "${APP_HOME}/realtime" ]]; then
  echo "Expected repo to live at ${APP_HOME}, but realtime dir is ${REALTIME_DIR}" >&2
  echo "Run install-snowman.sh or clone the repo into ${APP_HOME} first." >&2
  exit 1
fi

mkdir -p "${DATA_DIR}" "${DATA_DIR}/backups"

python3 "${REALTIME_DIR}/scripts/migrate_legacy_config.py" --data-dir "${DATA_DIR}" --legacy-env-file "${REALTIME_DIR}/.env"

if [[ ! -f "${DATA_DIR}/config.json" ]]; then
  cp "${REALTIME_DIR}/config.json" "${DATA_DIR}/config.json"
fi
if [[ ! -f "${DATA_DIR}/identity.md" ]]; then
  python3 - "${DATA_DIR}/identity.md" <<'EOF'
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from snowman_realtime.config import DEFAULT_SYSTEM_PROMPT

identity_path = Path(sys.argv[1])
identity_path.write_text(DEFAULT_SYSTEM_PROMPT + "\n", encoding="utf-8")
EOF
fi

generated_admin_password=""
if [[ ! -f "${DATA_DIR}/secrets.json" ]]; then
  printf '{}\n' > "${DATA_DIR}/secrets.json"
fi
if ! python3 - "${DATA_DIR}/secrets.json" <<'EOF'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("admin_password") else 1)
EOF
then
  generated_admin_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
  python3 - "${DATA_DIR}/secrets.json" "${generated_admin_password}" <<'EOF'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["admin_password"] = sys.argv[2]
path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
EOF
fi

python3 -m venv "${REALTIME_DIR}/venv"
"${REALTIME_DIR}/venv/bin/pip" install --upgrade pip wheel
"${REALTIME_DIR}/venv/bin/pip" install -r "${REALTIME_DIR}/requirements.txt"

chmod 755 \
  "${REALTIME_DIR}/scripts/start_realtime.sh" \
  "${REALTIME_DIR}/scripts/start_config_ui.sh" \
  "${REALTIME_DIR}/scripts/apply_config.sh" \
  "${REALTIME_DIR}/scripts/check_legacy_config_match.py" \
  "${REALTIME_DIR}/scripts/check_realtime_health.sh" \
  "${REALTIME_DIR}/scripts/within_runtime_window.sh" \
  "${REALTIME_DIR}/scripts/probe_realtime_connect.py" \
  "${REALTIME_DIR}/scripts/migrate_legacy_config.py"

render_template() {
  local template_file="$1"
  local output_file="$2"
  sed \
    -e "s|__DEPLOY_USER__|${USER}|g" \
    -e "s|__DEPLOY_HOME__|${HOME}|g" \
    -e "s|__DATA_DIR__|${DATA_DIR}|g" \
    -e "s|__REALTIME_DIR__|${REALTIME_DIR}|g" \
    "${template_file}" > "${output_file}"
}

install_template() {
  local template_file="$1"
  local dest_file="$2"
  local tmp_file
  tmp_file="$(mktemp)"
  render_template "${template_file}" "${tmp_file}"
  sudo install -m 644 "${tmp_file}" "${dest_file}"
  rm -f "${tmp_file}"
}

install_template "${REALTIME_DIR}/systemd/snowman-realtime.service.in" "/etc/systemd/system/snowman-realtime.service"
install_template "${REALTIME_DIR}/systemd/snowman-realtime-healthcheck.service.in" "/etc/systemd/system/snowman-realtime-healthcheck.service"
sudo install -m 644 "${REALTIME_DIR}/systemd/snowman-realtime-healthcheck.timer" "/etc/systemd/system/snowman-realtime-healthcheck.timer"
install_template "${REALTIME_DIR}/systemd/snowman-config-ui.service.in" "/etc/systemd/system/snowman-config-ui.service"

sudoers_tmp="$(mktemp)"
cat > "${sudoers_tmp}" <<EOF
${USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} daemon-reload
${USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} enable snowman-realtime.service
${USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} restart snowman-realtime.service
${USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} enable snowman-realtime-healthcheck.timer
${USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} start snowman-realtime-healthcheck.timer
EOF
sudo install -m 440 "${sudoers_tmp}" "/etc/sudoers.d/snowman-config-ui"
rm -f "${sudoers_tmp}"

sudo systemctl daemon-reload
sudo systemctl enable snowman-config-ui.service
sudo systemctl restart snowman-config-ui.service

host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${host_ip}" ]]; then
  host_ip="localhost"
fi

printf '\nSnowman config UI is ready.\n'
printf 'Open: http://%s:%s\n' "${host_ip}" "${CONFIG_UI_PORT}"
if [[ -n "${generated_admin_password}" ]]; then
  printf 'Admin password: %s\n' "${generated_admin_password}"
fi
printf 'Realtime service will start after you save valid configuration in the web UI.\n'
