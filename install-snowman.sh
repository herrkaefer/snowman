#!/usr/bin/env bash
set -euo pipefail

TARGET="realtime"
REPO_URL="${SNOWMAN_REPO_URL:-https://github.com/herrkaefer/snowman.git}"
BRANCH="${SNOWMAN_REPO_BRANCH:-main}"
INSTALL_DIR="${SNOWMAN_INSTALL_DIR:-$HOME/snowman-realtime}"

usage() {
  cat <<'EOF'
Usage: install-snowman.sh [--target realtime|pipeline] [--repo-url <url>] [--branch <branch>] [--install-dir <dir>]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="${2:-}"
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

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required for installation" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y git python3 python3-venv

if [[ -d "${INSTALL_DIR}/.git" ]]; then
  git -C "${INSTALL_DIR}" fetch --depth 1 origin "${BRANCH}"
  git -C "${INSTALL_DIR}" checkout "${BRANCH}"
  git -C "${INSTALL_DIR}" pull --ff-only origin "${BRANCH}"
else
  if [[ -e "${INSTALL_DIR}" ]]; then
    echo "Install dir already exists and is not a git repo: ${INSTALL_DIR}" >&2
    exit 1
  fi
  git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${INSTALL_DIR}"
fi

exec env SNOWMAN_APP_HOME="${INSTALL_DIR}" "${INSTALL_DIR}/realtime/scripts/bootstrap_pi.sh" --target "${TARGET}"
