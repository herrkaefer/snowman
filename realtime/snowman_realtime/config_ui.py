from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from .config import DEFAULT_SYSTEM_PROMPT
from .managed_config import (
    ManagedConfigPaths,
    editable_config_for_api,
    load_editable_config,
    merge_editable_config,
    missing_required_fields,
    resolve_managed_config_paths,
    validate_editable_config,
    write_managed_config,
)
from .version import VERSION


APP_DIR = Path(__file__).resolve().parents[1]
HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Snowman Config</title>
  <style>
    :root {
      --bg: #f3efe5;
      --panel: #fffaf2;
      --ink: #18211f;
      --muted: #55605c;
      --line: #d7cdbd;
      --accent: #0e6b5a;
      --accent-soft: #d6efe8;
      --warn: #a14a1c;
      --warn-soft: #fde9dd;
      --good: #25614c;
      --good-soft: #ddefe7;
      --shadow: rgba(24, 33, 31, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, #fff8ec, transparent 34%),
        radial-gradient(circle at top right, #dcefe9, transparent 28%),
        var(--bg);
      color: var(--ink);
    }
    .wrap {
      max-width: 1080px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }
    .hero {
      display: grid;
      gap: 10px;
      margin-bottom: 22px;
    }
    .hero h1 {
      margin: 0;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      max-width: 60ch;
    }
    .status {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 20px 0 24px;
    }
    .pill {
      padding: 9px 12px;
      border-radius: 999px;
      font-size: 0.95rem;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.65);
    }
    .pill.good { background: var(--good-soft); color: var(--good); border-color: #bfd8cb; }
    .pill.warn { background: var(--warn-soft); color: var(--warn); border-color: #e7c1ac; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 18px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: 0 14px 40px var(--shadow);
      padding: 18px;
    }
    .card h2 {
      margin: 0 0 6px;
      font-size: 1.1rem;
    }
    .card p {
      margin: 0 0 16px;
      color: var(--muted);
      font-size: 0.95rem;
    }
    label {
      display: block;
      font-weight: 600;
      font-size: 0.95rem;
      margin-bottom: 8px;
    }
    .required::after {
      content: " *";
      color: var(--warn);
    }
    input, select, textarea, button {
      font: inherit;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      background: white;
      color: var(--ink);
      margin-bottom: 14px;
    }
    textarea {
      min-height: 180px;
      resize: vertical;
    }
    .secret-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: start;
    }
    .secret-row button {
      margin-top: 0;
      min-width: 82px;
    }
    .hint {
      margin-top: -8px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 0.85rem;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 24px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 13px 18px;
      cursor: pointer;
      background: var(--accent);
      color: white;
      box-shadow: 0 10px 24px rgba(14, 107, 90, 0.18);
    }
    button.secondary {
      background: white;
      color: var(--ink);
      border: 1px solid var(--line);
      box-shadow: none;
    }
    .panel {
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.7);
      white-space: pre-wrap;
      min-height: 60px;
    }
    .panel.warn {
      background: var(--warn-soft);
      border-color: #e7c1ac;
      color: var(--warn);
    }
    .panel.good {
      background: var(--good-soft);
      border-color: #bfd8cb;
      color: var(--good);
    }
    @media (max-width: 720px) {
      .wrap { padding: 24px 14px 40px; }
      .secret-row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Snowman Control Surface</h1>
      <p>Use the same page for first-time setup and later updates. Required fields are marked clearly, and related settings stay grouped together.</p>
    </div>

    <div id="status-pills" class="status"></div>

    <div class="grid">
      <section class="card">
        <h2>AI Provider</h2>
        <p>Provider, credentials, and voice settings for realtime replies.</p>
        <label class="required" for="provider">Provider</label>
        <select id="provider">
          <option value="openai">OpenAI Realtime</option>
        </select>

        <label class="required" for="openai_api_key">OpenAI API Key</label>
        <div class="secret-row">
          <input id="openai_api_key" type="password" autocomplete="off" placeholder="Enter a new key or leave blank to keep the current one">
          <button id="toggle_openai_api_key" class="secondary" type="button">Show</button>
        </div>
        <div id="openai_api_key_hint" class="hint"></div>

        <label class="required" for="openai_voice">Voice</label>
        <input id="openai_voice" type="text" placeholder="alloy">
      </section>

      <section class="card">
        <h2>Assistant</h2>
        <p>Prompt and interaction defaults used by the realtime assistant.</p>
        <label class="required" for="system_prompt">System Prompt</label>
        <textarea id="system_prompt"></textarea>
      </section>

      <section class="card">
        <h2>Device / Wake Word</h2>
        <p>Local device credentials needed to detect the wake word on Raspberry Pi.</p>
        <label class="required" for="porcupine_access_key">Porcupine Access Key</label>
        <div class="secret-row">
          <input id="porcupine_access_key" type="password" autocomplete="off" placeholder="Enter a new key or leave blank to keep the current one">
          <button id="toggle_porcupine_access_key" class="secondary" type="button">Show</button>
        </div>
        <div id="porcupine_access_key_hint" class="hint"></div>
      </section>

      <section class="card">
        <h2>Location / Session</h2>
        <p>Optional defaults for location-aware answers and multi-turn follow-up mode.</p>
        <label for="location_city">City</label>
        <input id="location_city" type="text" placeholder="Chicago">

        <label for="location_region">Region / State</label>
        <input id="location_region" type="text" placeholder="IL">

        <label for="location_country_code">Country Code</label>
        <input id="location_country_code" type="text" placeholder="US">

        <label for="location_timezone">Timezone</label>
        <input id="location_timezone" type="text" placeholder="America/Chicago">

        <label for="session_window_enabled">Session Window</label>
        <select id="session_window_enabled">
          <option value="false">Single-turn</option>
          <option value="true">Session window enabled</option>
        </select>
      </section>
    </div>

    <div class="actions">
      <button id="validate" type="button">Validate</button>
      <button id="apply" type="button">Save And Restart</button>
    </div>

    <div id="message" class="panel">Loading configuration...</div>
  </div>

  <script>
    const fieldIds = [
      "provider",
      "openai_api_key",
      "openai_voice",
      "system_prompt",
      "porcupine_access_key",
      "location_city",
      "location_region",
      "location_country_code",
      "location_timezone",
      "session_window_enabled"
    ];

    function $(id) { return document.getElementById(id); }

    function setMessage(text, kind = "") {
      const node = $("message");
      node.textContent = text;
      node.className = "panel" + (kind ? " " + kind : "");
    }

    function payloadFromForm() {
      return {
        provider: $("provider").value,
        openai_api_key: $("openai_api_key").value,
        openai_voice: $("openai_voice").value,
        system_prompt: $("system_prompt").value,
        porcupine_access_key: $("porcupine_access_key").value,
        location_city: $("location_city").value,
        location_region: $("location_region").value,
        location_country_code: $("location_country_code").value,
        location_timezone: $("location_timezone").value,
        session_window_enabled: $("session_window_enabled").value === "true"
      };
    }

    function populateForm(config) {
      $("provider").value = config.provider || "openai";
      $("openai_voice").value = config.openai_voice || "";
      $("system_prompt").value = config.system_prompt || "";
      $("location_city").value = config.location_city || "";
      $("location_region").value = config.location_region || "";
      $("location_country_code").value = config.location_country_code || "";
      $("location_timezone").value = config.location_timezone || "";
      $("session_window_enabled").value = String(Boolean(config.session_window_enabled));
      $("openai_api_key").value = "";
      $("porcupine_access_key").value = "";
      $("openai_api_key_hint").textContent = config.openai_api_key_configured
        ? "A key is already saved. Leave blank to keep it."
        : "No key saved yet.";
      $("porcupine_access_key_hint").textContent = config.porcupine_access_key_configured
        ? "A key is already saved. Leave blank to keep it."
        : "No key saved yet.";
    }

    function renderStatus(status) {
      const pills = [];
      pills.push(`<div class="pill ${status.setup_state === "ready" ? "good" : "warn"}">Setup: ${status.setup_state}</div>`);
      pills.push(`<div class="pill ${status.service_state === "active" ? "good" : "warn"}">Realtime Service: ${status.service_state}</div>`);
      if (status.missing_required_fields.length) {
        pills.push(`<div class="pill warn">Missing: ${status.missing_required_fields.join(", ")}</div>`);
      }
      if (status.last_apply_message) {
        pills.push(`<div class="pill">Last Apply: ${status.last_apply_message}</div>`);
      }
      $("status-pills").innerHTML = pills.join("");
    }

    async function readJson(url, options = {}) {
      const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Request failed");
      }
      return payload;
    }

    async function refresh() {
      const [config, status] = await Promise.all([
        readJson("/api/config"),
        readJson("/api/status")
      ]);
      populateForm(config.config);
      renderStatus(status);
      setMessage("Configuration loaded.", "good");
    }

    async function validateConfig() {
      try {
        const result = await readJson("/api/config/validate", {
          method: "POST",
          body: JSON.stringify(payloadFromForm())
        });
        if (result.errors.length) {
          setMessage(result.errors.join("\\n"), "warn");
        } else {
          setMessage("Configuration looks valid.", "good");
        }
        renderStatus(result.status);
      } catch (error) {
        setMessage(error.message, "warn");
      }
    }

    async function applyConfig() {
      try {
        setMessage("Applying configuration and restarting realtime service...");
        const result = await readJson("/api/config/apply", {
          method: "POST",
          body: JSON.stringify(payloadFromForm())
        });
        populateForm(result.config);
        renderStatus(result.status);
        setMessage(result.message, "good");
      } catch (error) {
        setMessage(error.message, "warn");
      }
    }

    function wireSecretToggle(id) {
      const input = $(id);
      const button = $("toggle_" + id);
      button.addEventListener("click", () => {
        const hidden = input.type === "password";
        input.type = hidden ? "text" : "password";
        button.textContent = hidden ? "Hide" : "Show";
      });
    }

    $("validate").addEventListener("click", validateConfig);
    $("apply").addEventListener("click", applyConfig);
    wireSecretToggle("openai_api_key");
    wireSecretToggle("porcupine_access_key");

    refresh().catch((error) => {
      setMessage(error.message, "warn");
    });
  </script>
</body>
</html>
"""


class ConfigUIServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, ConfigUIHandler)
        self.last_apply_message = ""
        self.last_apply_ok = False


class ConfigUIHandler(BaseHTTPRequestHandler):
    server_version = f"SnowmanConfigUI/{VERSION}"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not self._check_auth():
            return
        if parsed.path == "/":
            self._write_html(HTML_PAGE)
            return
        if parsed.path == "/api/config":
            self._write_json({"config": editable_config_for_api(_load_current_config())})
            return
        if parsed.path == "/api/setup-state":
            self._write_json(_status_payload())
            return
        if parsed.path == "/api/status":
            self._write_json(_status_payload(last_apply_message=self.server.last_apply_message))
            return
        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._check_auth():
            return
        body = self._read_json_body()
        if body is None:
            return
        merged = merge_editable_config(_load_current_config(), body)
        if parsed.path == "/api/config/validate":
            errors = validate_editable_config(merged)
            self._write_json(
                {
                    "errors": errors,
                    "status": _status_payload(
                        config_payload=merged,
                        last_apply_message=self.server.last_apply_message,
                    ),
                }
            )
            return
        if parsed.path == "/api/config/apply":
            errors = validate_editable_config(merged)
            if errors:
                self._write_json(
                    {
                        "error": "\n".join(errors),
                        "errors": errors,
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                _apply_config(merged)
            except RuntimeError as exc:
                self.server.last_apply_ok = False
                self.server.last_apply_message = str(exc)
                self._write_json(
                    {"error": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return

            self.server.last_apply_ok = True
            self.server.last_apply_message = "Configuration applied successfully."
            self._write_json(
                {
                    "message": self.server.last_apply_message,
                    "config": editable_config_for_api(_load_current_config()),
                    "status": _status_payload(
                        last_apply_message=self.server.last_apply_message
                    ),
                }
            )
            return
        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _check_auth(self) -> bool:
        password = _load_current_config().get("admin_password", "")
        if not isinstance(password, str) or not password.strip():
            return True
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            self._write_auth_required()
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        except Exception:
            self._write_auth_required()
            return False
        _, _, supplied_password = decoded.partition(":")
        if not secrets.compare_digest(password, supplied_password):
            self._write_auth_required()
            return False
        return True

    def _write_auth_required(self) -> None:
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Snowman Config"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Authentication required"}).encode("utf-8"))

    def _read_json_body(self) -> dict[str, object] | None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._write_json({"error": "Invalid JSON payload"}, status=HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self._write_json({"error": "JSON body must be an object"}, status=HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def _write_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_json(self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    host = os.getenv("SNOWMAN_CONFIG_UI_HOST", "0.0.0.0").strip()
    port = int(os.getenv("SNOWMAN_CONFIG_UI_PORT", "3010"))
    server = ConfigUIServer((host, port))
    print(f"Snowman config UI listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def _load_env_values() -> dict[str, str]:
    values = {
        key: value
        for key, value in dotenv_values(APP_DIR / ".env").items()
        if key and value is not None
    }
    values.update(os.environ)
    return values


def _load_current_config() -> dict[str, object]:
    return load_editable_config(
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        env_values=_load_env_values(),
    )


def _status_payload(
    *,
    config_payload: dict[str, object] | None = None,
    last_apply_message: str = "",
) -> dict[str, object]:
    current = config_payload or _load_current_config()
    missing = missing_required_fields(current)
    service_state = _service_state(os.getenv("SNOWMAN_REALTIME_SERVICE", "snowman-realtime.service"))
    if missing:
        setup_state = "not_configured"
    elif service_state == "active":
        setup_state = "ready"
    else:
        setup_state = "configured_but_service_unhealthy"
    return {
        "setup_state": setup_state,
        "service_state": service_state,
        "missing_required_fields": missing,
        "last_apply_message": last_apply_message,
    }


def _service_state(service_name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return "unknown"
    state = (result.stdout or result.stderr).strip()
    return state or "unknown"


def _apply_config(payload: dict[str, object]) -> None:
    paths = resolve_managed_config_paths()
    temp_dir = paths.data_dir / ".tmp-config-ui"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_paths = ManagedConfigPaths(
        data_dir=temp_dir,
        config_path=temp_dir / "config.json",
        secrets_path=temp_dir / "secrets.env",
    )
    write_managed_config(temp_paths, payload)
    script_path = APP_DIR / "scripts" / "apply_managed_config.sh"
    result = subprocess.run(
        [
            str(script_path),
            "--config",
            str(temp_paths.config_path),
            "--secrets",
            str(temp_paths.secrets_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or "Failed to apply configuration")


if __name__ == "__main__":
    main()
