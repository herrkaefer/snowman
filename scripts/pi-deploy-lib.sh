#!/usr/bin/env bash

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  local cmd
  for cmd in "$@"; do
    command -v "${cmd}" >/dev/null 2>&1 || fail "Missing required command: ${cmd}"
  done
}

quote_remote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

ssh_pi() {
  ssh -o StrictHostKeyChecking=no -p "${PI_PORT}" "${PI_USER}@${PI_HOST}" "$@"
}

scp_pi() {
  scp -o StrictHostKeyChecking=no -P "${PI_PORT}" "$@"
}

run_remote() {
  local command="$1"
  ssh_pi "${command}"
}

copy_dir_contents_to_remote() {
  local src_dir="$1"
  local dest_dir="$2"
  COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.DS_Store' \
    --exclude='._*' \
    --exclude='.env' \
    -C "${src_dir}" \
    -cf - . | ssh_pi "mkdir -p $(quote_remote "${dest_dir}") && tar -xf - -C $(quote_remote "${dest_dir}")"
}

copy_file_to_remote() {
  local src_file="$1"
  local dest_file="$2"
  scp_pi "${src_file}" "${PI_USER}@${PI_HOST}:${dest_file}"
}

install_file_to_remote() {
  local src_file="$1"
  local mode="$2"
  local dest_file="$3"
  local remote_tmp="/tmp/$(basename "${src_file}").$$"
  copy_file_to_remote "${src_file}" "${remote_tmp}"
  run_remote "sudo install -m ${mode} $(quote_remote "${remote_tmp}") $(quote_remote "${dest_file}") && rm -f $(quote_remote "${remote_tmp}")"
}

render_template_to_file() {
  local template_file="$1"
  local output_file="$2"
  sed \
    -e "s|__DEPLOY_USER__|${PI_USER}|g" \
    -e "s|__DEPLOY_HOME__|${DEPLOY_HOME}|g" \
    -e "s|__PIPELINE_DIR__|${PIPELINE_REMOTE_DIR:-}|g" \
    -e "s|__REALTIME_DIR__|${REALTIME_REMOTE_DIR:-}|g" \
    "${template_file}" > "${output_file}"
}

install_rendered_template_to_remote() {
  local template_file="$1"
  local mode="$2"
  local dest_file="$3"
  local local_tmp
  local_tmp="$(mktemp)"
  render_template_to_file "${template_file}" "${local_tmp}"
  install_file_to_remote "${local_tmp}" "${mode}" "${dest_file}"
  rm -f "${local_tmp}"
}

show_remote_status() {
  local service_name="$1"
  run_remote "sudo systemctl status $(quote_remote "${service_name}") --no-pager"
}
