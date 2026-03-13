#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${SNOWMAN_DATA_DIR:-${APP_DIR}/../data}"
CONFIG_PATH=""
SECRETS_PATH=""
IDENTITY_PATH=""
SERVICE_NAME="${SNOWMAN_REALTIME_SERVICE:-snowman-realtime.service}"
HEALTHCHECK_TIMER="${SNOWMAN_HEALTHCHECK_TIMER:-snowman-realtime-healthcheck.timer}"
SYSTEMCTL_BIN="$(command -v systemctl)"

usage() {
  cat <<'EOF'
Usage: apply_config.sh --config <config.json> --secrets <secrets.json> --identity <identity.md>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
    --secrets)
      SECRETS_PATH="${2:-}"
      shift 2
      ;;
    --identity)
      IDENTITY_PATH="${2:-}"
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

[[ -n "${CONFIG_PATH}" ]] || { echo "--config is required" >&2; exit 1; }
[[ -n "${SECRETS_PATH}" ]] || { echo "--secrets is required" >&2; exit 1; }
[[ -n "${IDENTITY_PATH:-}" ]] || { echo "--identity is required" >&2; exit 1; }
[[ -f "${CONFIG_PATH}" ]] || { echo "Config file not found: ${CONFIG_PATH}" >&2; exit 1; }
[[ -f "${SECRETS_PATH}" ]] || { echo "Secrets file not found: ${SECRETS_PATH}" >&2; exit 1; }
[[ -f "${IDENTITY_PATH}" ]] || { echo "Identity file not found: ${IDENTITY_PATH}" >&2; exit 1; }

mkdir -p "${DATA_DIR}" "${DATA_DIR}/backups"

TARGET_CONFIG="${DATA_DIR}/config.json"
TARGET_SECRETS="${DATA_DIR}/secrets.json"
TARGET_IDENTITY="${DATA_DIR}/identity.md"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
BACKUP_CONFIG="${DATA_DIR}/backups/config-${TIMESTAMP}.json"
BACKUP_SECRETS="${DATA_DIR}/backups/secrets-${TIMESTAMP}.json"
BACKUP_IDENTITY="${DATA_DIR}/backups/identity-${TIMESTAMP}.md"

if [[ -f "${TARGET_CONFIG}" ]]; then
  cp "${TARGET_CONFIG}" "${BACKUP_CONFIG}"
fi
if [[ -f "${TARGET_SECRETS}" ]]; then
  cp "${TARGET_SECRETS}" "${BACKUP_SECRETS}"
fi
if [[ -f "${TARGET_IDENTITY}" ]]; then
  cp "${TARGET_IDENTITY}" "${BACKUP_IDENTITY}"
fi

cp "${CONFIG_PATH}" "${TARGET_CONFIG}.next"
cp "${SECRETS_PATH}" "${TARGET_SECRETS}.next"
cp "${IDENTITY_PATH}" "${TARGET_IDENTITY}.next"
mv "${TARGET_CONFIG}.next" "${TARGET_CONFIG}"
mv "${TARGET_SECRETS}.next" "${TARGET_SECRETS}"
mv "${TARGET_IDENTITY}.next" "${TARGET_IDENTITY}"

restart_failed=0
if ! sudo -n "${SYSTEMCTL_BIN}" daemon-reload; then
  echo "Failed to reload systemd" >&2
  exit 1
fi
if ! sudo -n "${SYSTEMCTL_BIN}" enable "${SERVICE_NAME}" >/dev/null 2>&1; then
  echo "Failed to enable ${SERVICE_NAME}" >&2
  restart_failed=1
fi
if [[ "${restart_failed}" -eq 0 ]] && ! sudo -n "${SYSTEMCTL_BIN}" restart "${SERVICE_NAME}"; then
  echo "Failed to restart ${SERVICE_NAME}" >&2
  restart_failed=1
fi
if [[ "${restart_failed}" -eq 0 ]] && ! sudo -n "${SYSTEMCTL_BIN}" enable "${HEALTHCHECK_TIMER}" >/dev/null 2>&1; then
  echo "Failed to enable ${HEALTHCHECK_TIMER}" >&2
  restart_failed=1
fi
if [[ "${restart_failed}" -eq 0 ]] && ! sudo -n "${SYSTEMCTL_BIN}" start "${HEALTHCHECK_TIMER}"; then
  echo "Failed to start ${HEALTHCHECK_TIMER}" >&2
  restart_failed=1
fi

if [[ "${restart_failed}" -eq 0 ]]; then
  service_state="$("${SYSTEMCTL_BIN}" is-active "${SERVICE_NAME}" || true)"
  if [[ "${service_state}" != "active" ]]; then
    echo "Realtime service did not become active: ${service_state}" >&2
    restart_failed=1
  fi
fi

if [[ "${restart_failed}" -eq 1 ]]; then
  if [[ -f "${BACKUP_CONFIG}" ]]; then
    cp "${BACKUP_CONFIG}" "${TARGET_CONFIG}"
  else
    rm -f "${TARGET_CONFIG}"
  fi
  if [[ -f "${BACKUP_SECRETS}" ]]; then
    cp "${BACKUP_SECRETS}" "${TARGET_SECRETS}"
  else
    rm -f "${TARGET_SECRETS}"
  fi
  if [[ -f "${BACKUP_IDENTITY}" ]]; then
    cp "${BACKUP_IDENTITY}" "${TARGET_IDENTITY}"
  else
    rm -f "${TARGET_IDENTITY}"
  fi
  sudo -n "${SYSTEMCTL_BIN}" restart "${SERVICE_NAME}" >/dev/null 2>&1 || true
  exit 1
fi
