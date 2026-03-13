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

from .audio import (
    list_input_devices,
    list_playback_devices,
    play_speaker_test,
    resolve_input_device_index,
    resolve_playback_device,
    sample_microphone_level,
)
from .config import DEFAULT_SYSTEM_PROMPT
from .config_store import (
    DEFAULT_MEMORY_DIR,
    ConfigPaths,
    config_values_for_api,
    load_config_values,
    merge_config_values,
    missing_required_fields,
    resolve_config_paths,
    validate_config_values,
    write_config_files,
)
from .memory import MemoryStore
from .tools import build_tool_definitions
from .version import VERSION


APP_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = APP_DIR / "ui_assets"
HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Snowman Config</title>
  <style>
    :root {
      --bg: #9dc5db;
      --bg-deep: #6f9cb8;
      --panel: #edf7ff;
      --panel-alt: #fff6d6;
      --ink: #16304c;
      --muted: #4f6980;
      --line: #16304c;
      --accent: #ff7f50;
      --accent-press: #e2683b;
      --warn: #9c3d24;
      --warn-soft: #ffd3be;
      --good: #1f6651;
      --good-soft: #d2f1e7;
      --pixel-shadow: 0 6px 0 rgba(22, 48, 76, 0.18);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Courier New", "Lucida Console", monospace;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.25), transparent 22%),
        linear-gradient(0deg, rgba(255,255,255,0.18), transparent 28%),
        linear-gradient(90deg, rgba(255,255,255,0.14) 1px, transparent 1px),
        linear-gradient(rgba(255,255,255,0.14) 1px, transparent 1px),
        linear-gradient(180deg, var(--bg), var(--bg-deep));
      background-size: auto, auto, 20px 20px, 20px 20px, auto;
      color: var(--ink);
    }
    .wrap {
      max-width: 980px;
      margin: 0 auto;
      padding: 28px 16px 52px;
    }
    .hero {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      gap: 12px;
      margin-bottom: 24px;
    }
    .logo-shell {
      width: min(240px, 52vw);
      padding: 12px;
      border: 4px solid var(--line);
      background: var(--panel-alt);
      box-shadow: var(--pixel-shadow);
    }
    .logo-shell img {
      display: block;
      width: 100%;
      height: auto;
      image-rendering: pixelated;
    }
    .hero h1 {
      margin: 0;
      font-size: clamp(1.8rem, 4vw, 2.9rem);
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }
    .status-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin: 0 0 20px;
    }
    .status {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      flex: 1 1 520px;
    }
    .pill {
      padding: 8px 12px;
      font-size: 0.84rem;
      border: 2px solid rgba(22, 48, 76, 0.42);
      background: rgba(255, 255, 255, 0.68);
      color: var(--muted);
      box-shadow: none;
      border-radius: 0;
      text-transform: uppercase;
    }
    .pill.good {
      background: #d7efe4;
      color: var(--good);
      border-color: rgba(53, 107, 87, 0.55);
    }
    .pill.warn {
      background: #ffe1cf;
      color: var(--warn);
      border-color: rgba(138, 71, 47, 0.55);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: flex-end;
      flex: 0 0 auto;
    }
    .tabs {
      display: flex;
      gap: 8px;
      margin: 0 0 -4px;
      padding: 0 12px;
      align-items: flex-end;
    }
    .tab {
      position: relative;
      top: 4px;
      border: 4px solid var(--line);
      border-bottom-width: 0;
      border-radius: 10px 10px 0 0;
      background: #c8dceb;
      color: var(--muted);
      padding: 12px 18px 14px;
      box-shadow: 4px 0 0 rgba(22, 48, 76, 0.12);
      font-weight: 700;
      text-transform: uppercase;
      cursor: pointer;
    }
    .tab.active {
      background: var(--panel-alt);
      color: var(--ink);
      box-shadow: none;
      z-index: 2;
    }
    .tab:hover {
      transform: none;
      box-shadow: 4px 0 0 rgba(22, 48, 76, 0.12);
      background: #d8e7f2;
      color: var(--ink);
    }
    .tab:active {
      transform: none;
      box-shadow: none;
      background: #d8e7f2;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
      border-top: 4px solid var(--line);
      padding-top: 18px;
    }
    .card {
      background: var(--panel);
      border: 4px solid var(--line);
      box-shadow: var(--pixel-shadow);
      padding: 20px;
    }
    .card h2 {
      margin: 0 0 8px;
      font-size: 1.15rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .section-title {
      margin: 18px 0 8px;
      font-size: 1rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 700;
    }
    .section-title:first-of-type {
      margin-top: 0;
    }
    .card p {
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }
    label {
      display: block;
      font-weight: 600;
      font-size: 0.9rem;
      margin-bottom: 8px;
      text-transform: uppercase;
    }
    .field-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .secret-state {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      padding: 5px 10px;
      border: 3px solid var(--line);
      background: #d8e7f2;
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .secret-state.saved {
      background: var(--good-soft);
      color: var(--good);
    }
    .secret-state.missing {
      background: var(--warn-soft);
      color: var(--warn);
    }
    .required::after {
      content: " [*]";
      color: var(--warn);
    }
    input, select, textarea, button {
      font: inherit;
    }
    input, select, textarea {
      width: 100%;
      border: 3px solid var(--line);
      padding: 14px 16px;
      background: white;
      color: var(--ink);
      margin-bottom: 14px;
      box-shadow: inset 2px 2px 0 rgba(22, 48, 76, 0.08);
    }
    textarea {
      min-height: 240px;
      resize: vertical;
      line-height: 1.5;
      overflow: hidden;
    }
    #system_prompt {
      min-height: 620px;
    }
    #advanced_json {
      min-height: 120px;
      resize: none;
    }
    .file-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: start;
    }
    .split-fields {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      align-items: start;
    }
    .split-fields > div {
      min-width: 0;
    }
    .quad-fields {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      align-items: start;
    }
    .quad-fields > div {
      min-width: 0;
    }
    .file-row button {
      margin-top: 0;
      min-width: 82px;
    }
    .device-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
    }
    .device-row button {
      margin-top: 0;
      min-width: 140px;
    }
    .test-result {
      margin-top: -8px;
      margin-bottom: 14px;
      min-height: 22px;
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.45;
    }
    .test-result.good {
      color: var(--good);
    }
    .test-result.warn {
      color: var(--warn);
    }
    .hint {
      margin-top: -8px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.45;
    }
    .hint a {
      color: var(--ink);
      font-weight: 700;
    }
    button {
      border: 3px solid var(--line);
      padding: 13px 18px;
      cursor: pointer;
      background: var(--accent);
      color: var(--line);
      font-weight: 700;
      text-transform: uppercase;
      box-shadow: 4px 4px 0 rgba(22, 48, 76, 0.22);
    }
    button:hover {
      transform: translate(1px, 1px);
      box-shadow: 3px 3px 0 rgba(22, 48, 76, 0.22);
    }
    button:active {
      transform: translate(4px, 4px);
      box-shadow: none;
      background: var(--accent-press);
    }
    button.secondary {
      background: var(--panel-alt);
      color: var(--ink);
      box-shadow: 4px 4px 0 rgba(22, 48, 76, 0.12);
    }
    .panel {
      margin-top: 18px;
      padding: 16px 18px;
      border: 4px solid var(--line);
      background: var(--panel);
      white-space: pre-wrap;
      min-height: 60px;
      box-shadow: var(--pixel-shadow);
      line-height: 1.45;
    }
    .panel.warn {
      background: var(--warn-soft);
      color: var(--warn);
    }
    .panel.good {
      background: var(--good-soft);
      color: var(--good);
    }
    .stack {
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
    }
    .tool-list {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }
    .tool-item {
      padding: 14px;
      border: 3px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
    }
    .tool-item h3 {
      margin: 0 0 6px;
      font-size: 0.96rem;
      text-transform: uppercase;
    }
    .tool-item p {
      margin: 0;
    }
    .hidden { display: none; }
    @media (max-width: 720px) {
      .wrap { padding: 22px 12px 38px; }
      .status-bar { flex-direction: column; }
      .actions { justify-content: flex-start; }
      .file-row { grid-template-columns: 1fr; }
      .device-row { grid-template-columns: 1fr; }
      .split-fields { grid-template-columns: 1fr; }
      .quad-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      #system_prompt { min-height: 480px; }
      #advanced_json { min-height: 120px; }
      .tabs { flex-wrap: wrap; }
    }
    @media (max-width: 520px) {
      .quad-fields { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="logo-shell">
        <img src="/assets/snowman_retro.svg" alt="Snowman logo">
      </div>
      <h1>Snowman Config</h1>
    </div>

    <div class="status-bar">
      <div id="status-pills" class="status"></div>
      <div class="actions">
        <button id="validate" type="button">Validate</button>
        <button id="apply" type="button">Save And Restart</button>
      </div>
    </div>

    <div class="tabs">
      <button id="tab_identity" class="tab active" type="button">Identity</button>
      <button id="tab_ai" class="tab" type="button">AI</button>
      <button id="tab_audio" class="tab" type="button">Audio</button>
      <button id="tab_tools" class="tab" type="button">Tools</button>
      <button id="tab_memory" class="tab" type="button">Memory</button>
      <button id="tab_advanced" class="tab" type="button">Advanced</button>
    </div>

    <div id="panel_identity" class="grid">
      <section class="card">
        <h2>Identity</h2>
        <p>Set the assistant's name, default local context, and speaking instructions.</p>
        <div class="section-title">Name</div>
        <input id="agent_name" type="text" placeholder="Snowman">

        <div class="section-title">Location</div>
        <p>Optional default location for local questions. It is also passed into system instructions to help with local context.</p>
        <label for="location_street">Street / Area</label>
        <input id="location_street" type="text" placeholder="123 Main St or W Belmont Ave">

        <div class="quad-fields">
          <div>
            <label for="location_city">City</label>
            <input id="location_city" type="text" placeholder="Chicago">
          </div>
          <div>
            <label for="location_region">Region / State</label>
            <input id="location_region" type="text" placeholder="IL">
          </div>
          <div>
            <label for="location_country_code">Country</label>
            <select id="location_country_code"></select>
          </div>
          <div>
            <label for="location_timezone">Time Zone</label>
            <select id="location_timezone"></select>
          </div>
        </div>

        <label class="required" for="system_prompt">Prompt</label>
        <textarea id="system_prompt"></textarea>
      </section>
    </div>

    <div id="panel_ai" class="grid hidden">
      <section class="card">
        <h2>AI Provider</h2>
        <p>Choose the AI provider and its current model, API key, and voice settings.</p>
        <label class="required" for="provider">Provider</label>
        <select id="provider"></select>

        <div class="field-head">
          <label class="required" for="openai_api_key">API Key</label>
          <div id="openai_api_key_state" class="secret-state missing">Missing</div>
        </div>
        <input id="openai_api_key" type="text" autocomplete="off" spellcheck="false" placeholder="Enter a new key or leave blank to keep the current one">
        <div id="openai_api_key_hint" class="hint"></div>

        <div class="split-fields">
          <div>
            <label class="required" for="openai_realtime_model">Realtime Model</label>
            <select id="openai_realtime_model"></select>
          </div>
          <div>
            <label class="required" for="openai_voice">Voice</label>
            <select id="openai_voice"></select>
          </div>
        </div>
      </section>
    </div>

    <div id="panel_audio" class="grid hidden">
      <section class="card">
        <h2>Wake Word & Audio</h2>
        <p>Set wake word detection and playback loudness for speech replies and short cue sounds.</p>
        <div class="field-head">
          <label class="required" for="porcupine_access_key">Porcupine Access Key</label>
          <div id="porcupine_access_key_state" class="secret-state missing">Missing</div>
        </div>
        <input id="porcupine_access_key" type="text" autocomplete="off" spellcheck="false" placeholder="Enter a new key or leave blank to keep the current one">
        <div id="porcupine_access_key_hint" class="hint"></div>
        <div class="hint">Get your key from <a href="https://console.picovoice.ai/" target="_blank" rel="noreferrer">Picovoice Console</a>. Create a Porcupine access key there, then paste it here.</div>

        <label class="required" for="wake_word_model">Wake Word Model (.ppn)</label>
        <input id="custom_wake_keyword_path" type="hidden">
        <div class="file-row">
          <input id="wake_word_model" type="file" accept=".ppn">
          <button id="upload_wake_word_model" class="secondary" type="button">Upload</button>
        </div>
        <div id="wake_word_model_hint" class="hint">Required. Snowman no longer ships with a default wake word model. Upload your own `.ppn` file from Picovoice Console. Porcupine also supports official built-in wake words such as `porcupine` and `jarvis`, but Snowman does not expose that mode yet.</div>

        <label for="wake_word_sensitivity">Wake Word Sensitivity</label>
        <input id="wake_word_sensitivity" type="number" min="0" max="1" step="0.05" placeholder="0.5">
        <div class="hint">Use a value from 0.0 to 1.0. Higher values reduce misses but increase false triggers.</div>

        <label for="output_gain">Reply Volume</label>
        <input id="output_gain" type="number" min="0" step="0.05" placeholder="0.5">
        <div class="hint">Controls assistant speech playback loudness. `1.0` is original volume, `0.5` is half volume. Recommended: `0.2` to `1.0`.</div>

        <label for="cue_output_gain">Cue Volume</label>
        <input id="cue_output_gain" type="number" min="0" step="0.05" placeholder="0.22">
        <div class="hint">Controls short cue sounds such as ready and end chimes. `1.0` is original volume. Recommended: `0.2` to `1.2`.</div>
      </section>

      <section class="card">
        <h2>Audio Devices</h2>
        <p>Choose which microphone and speaker Snowman should use. These can be different devices.</p>

        <label for="audio_device_index">Microphone Input</label>
        <div class="device-row">
          <select id="audio_device_index"></select>
          <button id="test_microphone" class="secondary" type="button">Test Microphone</button>
        </div>
        <div class="hint">The microphone test records a short sample and reports the input level it detects.</div>
        <div id="test_microphone_result" class="test-result"></div>

        <label for="playback_device">Speaker Output</label>
        <div class="device-row">
          <select id="playback_device"></select>
          <button id="test_speaker" class="secondary" type="button">Test Speaker</button>
        </div>
        <div class="hint">The speaker test plays a short cue through the selected output device.</div>
        <div id="test_speaker_result" class="test-result"></div>
      </section>
    </div>

    <div id="panel_advanced" class="grid hidden">
      <section class="card">
        <h2>Advanced Configuration</h2>
        <p>Edit the JSON directly if you need to tune models, audio devices, turn timing, gain, retries, or health checks.</p>
        <label for="advanced_json">Advanced Settings JSON</label>
        <textarea id="advanced_json"></textarea>
      </section>
    </div>

    <div id="panel_tools" class="grid hidden">
      <section class="card">
        <h2>Tools</h2>
        <p>Inspect the currently available runtime tools. Memory tools appear when memory is enabled.</p>
        <div id="tools_list" class="tool-list"></div>
      </section>
    </div>

    <div id="panel_memory" class="grid hidden">
      <section class="card">
        <h2>Memory</h2>
        <p>Inspect and edit profile memory. `MEMORY.md` is generated automatically and shown read-only as the prompt-visible memory index.</p>
        <div id="memory_status" class="hint"></div>
        <div id="memory_feedback" class="panel hidden"></div>
        <div class="stack">
          <div>
            <div class="field-head">
              <label for="profile_markdown">profile.md</label>
              <div>
                <button id="save_profile_memory" class="secondary" type="button">Save</button>
                <button id="save_profile_baseline" class="secondary" type="button">Save Current As Baseline</button>
                <button id="restore_profile_baseline" class="secondary" type="button">Restore Baseline</button>
              </div>
            </div>
            <textarea id="profile_markdown"></textarea>
          </div>
          <div>
            <div class="field-head">
              <label for="memory_index_markdown">MEMORY.md</label>
              <button id="save_memory_index" class="secondary" type="button">Save</button>
            </div>
            <textarea id="memory_index_markdown" readonly></textarea>
          </div>
        </div>
      </section>
    </div>

    <div id="message" class="panel">Loading configuration...</div>
  </div>

  <script>
    function $(id) { return document.getElementById(id); }

    function setMessage(text, kind = "") {
      const node = $("message");
      node.textContent = text;
      node.className = "panel" + (kind ? " " + kind : "");
    }

    function payloadFromForm() {
      let advanced;
      try {
        advanced = JSON.parse($("advanced_json").value || "{}");
      } catch (error) {
        setMessage(`Advanced settings JSON is invalid: ${error.message}`, "warn");
        return null;
      }
      if (!advanced || typeof advanced !== "object" || Array.isArray(advanced)) {
        setMessage("Advanced settings JSON must be an object.", "warn");
        return null;
      }
      advanced.audio_device_index = Number.parseInt($("audio_device_index").value || "-1", 10);
      if (Number.isNaN(advanced.audio_device_index)) {
        advanced.audio_device_index = -1;
      }
      advanced.playback_device = $("playback_device").value || "auto";
      return {
        agent_name: $("agent_name").value,
        provider: $("provider").value,
        openai_api_key: $("openai_api_key").value,
        openai_realtime_model: $("openai_realtime_model").value,
        openai_voice: $("openai_voice").value,
        system_prompt: $("system_prompt").value,
        location_street: $("location_street").value,
        wake_word_sensitivity: $("wake_word_sensitivity").value,
        output_gain: $("output_gain").value,
        cue_output_gain: $("cue_output_gain").value,
        porcupine_access_key: $("porcupine_access_key").value,
        custom_wake_keyword_path: $("custom_wake_keyword_path").value,
        location_city: $("location_city").value,
        location_region: $("location_region").value,
        location_country_code: $("location_country_code").value,
        location_timezone: $("location_timezone").value,
        advanced
      };
    }

    function populateForm(config) {
      renderSelectOptions("provider", config.provider_options || [], config.provider || "openai", {
        openai: "OpenAI"
      });
      renderSelectOptions("openai_realtime_model", config.openai_realtime_model_options || [], config.openai_realtime_model || "");
      renderSelectOptions("openai_voice", config.openai_voice_options || [], config.openai_voice || "");
      renderSelectOptions("audio_device_index", config.audio_input_options || [], String(config.audio_device_index ?? -1));
      renderSelectOptions("playback_device", config.audio_output_options || [], config.playback_device || "auto");
      renderSelectOptions("location_country_code", config.country_options || [], config.location_country_code || "", {
        "": "Select a country"
      });
      $("agent_name").value = config.agent_name || "Snowman";
      $("system_prompt").value = config.system_prompt || "";
      renderSelectOptions("location_timezone", config.timezone_options || [], config.location_timezone || "", {
        "": "Use Raspberry Pi timezone"
      });
      $("location_street").value = config.location_street || "";
      $("wake_word_sensitivity").value = config.wake_word_sensitivity ?? 0.5;
      $("output_gain").value = config.output_gain ?? 0.5;
      $("cue_output_gain").value = config.cue_output_gain ?? 0.22;
      $("custom_wake_keyword_path").value = config.custom_wake_keyword_path || "";
      $("location_city").value = config.location_city || "";
      $("location_region").value = config.location_region || "";
      $("advanced_json").value = JSON.stringify(config.advanced || {}, null, 2);
      $("openai_api_key").value = "";
      $("porcupine_access_key").value = "";
      $("wake_word_model").value = "";
      setTestResult("test_microphone_result", "");
      setTestResult("test_speaker_result", "");
      setSecretState(
        "openai_api_key",
        config.openai_api_key_configured,
        config.openai_api_key_masked || ""
      );
      setSecretState(
        "porcupine_access_key",
        config.porcupine_access_key_configured,
        config.porcupine_access_key_masked || ""
      );
      $("wake_word_model_hint").textContent = config.custom_wake_keyword_configured
        ? `Uploaded model: ${config.custom_wake_keyword_name}`
        : "Required. Upload your own .ppn wake word model from Picovoice Console.";
      autoGrowPrompt();
      autoGrowAdvanced();
    }

    function renderTools(tools) {
      const items = Array.isArray(tools) ? tools : [];
      $("tools_list").innerHTML = items
        .map((tool) => `
          <div class="tool-item">
            <h3>${tool.name}</h3>
            <p>${tool.description}</p>
          </div>
        `)
        .join("");
    }

    function populateMemory(memory) {
      $("profile_markdown").value = memory.profile_markdown || "";
      $("memory_index_markdown").value = memory.memory_index_markdown || "";
      $("memory_status").textContent = memory.memory_enabled
        ? `Memory is enabled. Storage: ${memory.memory_dir}. Baseline: ${memory.baseline_exists ? "saved" : "not saved"}.`
        : `Memory is disabled in runtime config. You can still inspect and edit files here. Storage: ${memory.memory_dir}. Baseline: ${memory.baseline_exists ? "saved" : "not saved"}.`;
      autoGrowProfile();
      autoGrowMemoryIndex();
    }

    function setMemoryFeedback(text, kind = "") {
      const node = $("memory_feedback");
      if (!text) {
        node.textContent = "";
        node.className = "panel hidden";
        return;
      }
      node.textContent = text;
      node.className = "panel" + (kind ? " " + kind : "");
    }

    function renderSelectOptions(id, values, selectedValue, labels = {}) {
      const select = $(id);
      const options = Array.isArray(values) ? values : [];
      select.innerHTML = options
        .map((item) => {
          const value = typeof item === "string" ? item : String(item.value || "");
          const selected = value === selectedValue ? " selected" : "";
          const label = typeof item === "string" ? (labels[value] || value) : String(item.label || value);
          return `<option value="${value}"${selected}>${label}</option>`;
        })
        .join("");
      const optionValues = options.map((item) => (typeof item === "string" ? item : String(item.value || "")));
      if (selectedValue && !optionValues.includes(selectedValue)) {
        select.innerHTML += `<option value="${selectedValue}" selected>${selectedValue}</option>`;
      }
      if (!select.value && selectedValue) {
        select.value = selectedValue;
      }
    }

    function setSecretState(id, configured, maskedValue) {
      const state = $(id + "_state");
      const hint = $(id + "_hint");
      state.className = "secret-state " + (configured ? "saved" : "missing");
      state.textContent = configured ? "Saved" : "Missing";
      hint.textContent = configured
        ? `Saved key: ${maskedValue}. Leave blank to keep it.`
        : "No key saved yet.";
    }

    function setTestResult(id, text, kind = "") {
      const node = $(id);
      node.textContent = text;
      node.className = "test-result" + (kind ? " " + kind : "");
    }

    function renderStatus(status) {
      const pills = [];
      pills.push(`<div class="pill ${status.setup_state === "ready" ? "good" : "warn"}">Config: ${status.setup_state}</div>`);
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

    function renderApplyingStatus() {
      renderStatus({
        setup_state: "applying",
        service_state: "restarting",
        missing_required_fields: [],
        last_apply_message: "Applying configuration and restarting realtime service...",
      });
    }

    async function refresh() {
      const [config, status, tools, memory] = await Promise.all([
        readJson("/api/config"),
        readJson("/api/status"),
        readJson("/api/tools"),
        readJson("/api/memory")
      ]);
      populateForm(config.config);
      renderStatus(status);
      renderTools(tools.tools);
      populateMemory(memory);
      setMemoryFeedback("");
      setMessage("Configuration loaded.", "good");
    }

    async function validateConfig() {
      const payload = payloadFromForm();
      if (!payload) {
        return;
      }
      try {
        const result = await readJson("/api/config/validate", {
          method: "POST",
          body: JSON.stringify(payload)
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
      const payload = payloadFromForm();
      if (!payload) {
        return;
      }
      try {
        $("validate").disabled = true;
        $("apply").disabled = true;
        $("save_profile_memory").disabled = true;
        $("save_profile_baseline").disabled = true;
        $("restore_profile_baseline").disabled = true;
        $("save_memory_index").disabled = true;
        const memoryResult = await readJson("/api/memory/profile", {
          method: "POST",
          body: JSON.stringify({
            profile_markdown: $("profile_markdown").value
          })
        });
        populateMemory(memoryResult);
        setMemoryFeedback("Profile memory saved.", "good");
        renderApplyingStatus();
        setMessage("Applying configuration and restarting realtime service...");
        const result = await readJson("/api/config/apply", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        populateForm(result.config);
        renderStatus(result.status);
        renderTools(result.tools || []);
        const memory = await readJson("/api/memory");
        populateMemory(memory);
        setMessage(result.message, "good");
      } catch (error) {
        setMemoryFeedback(error.message, "warn");
        setMessage(error.message, "warn");
        try {
          const status = await readJson("/api/status");
          renderStatus(status);
        } catch (_ignored) {
        }
      } finally {
        $("validate").disabled = false;
        $("apply").disabled = false;
        $("save_profile_memory").disabled = false;
        $("save_profile_baseline").disabled = false;
        $("restore_profile_baseline").disabled = false;
        $("save_memory_index").disabled = false;
      }
    }

    async function uploadWakeWordModel() {
      const input = $("wake_word_model");
      const file = input.files && input.files[0];
      if (!file) {
        setMessage("Choose a .ppn file before uploading.", "warn");
        return;
      }
      const bytes = await file.arrayBuffer();
      let binary = "";
      const view = new Uint8Array(bytes);
      for (const byte of view) {
        binary += String.fromCharCode(byte);
      }
      try {
        setMessage("Uploading wake word model...");
        const result = await readJson("/api/wake-word/upload", {
          method: "POST",
          body: JSON.stringify({
            filename: file.name,
            content_base64: btoa(binary)
          })
        });
        $("custom_wake_keyword_path").value = result.custom_wake_keyword_path;
        $("wake_word_model_hint").textContent = `Uploaded model: ${result.custom_wake_keyword_name}`;
        setMessage("Wake word model uploaded. Save and restart to apply it.", "good");
      } catch (error) {
        setMessage(error.message, "warn");
      }
    }

    async function testSpeaker() {
      const payload = payloadFromForm();
      if (!payload) {
        return;
      }
      setTestResult("test_speaker_result", "Playing test sound...", "");
      try {
        const result = await readJson("/api/audio-test/speaker", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        setTestResult("test_speaker_result", result.message || "Speaker test played.", "good");
      } catch (error) {
        setTestResult("test_speaker_result", error.message, "warn");
      }
    }

    async function testMicrophone() {
      const payload = payloadFromForm();
      if (!payload) {
        return;
      }
      setTestResult("test_microphone_result", "Listening for microphone input...", "");
      try {
        const result = await readJson("/api/audio-test/microphone", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        const message = result.detected_sound
          ? `Detected microphone input on ${result.device_name}. Peak level: ${result.peak_rms}.`
          : `Microphone opened on ${result.device_name}, but input stayed quiet. Peak level: ${result.peak_rms}.`;
        setTestResult("test_microphone_result", message, result.detected_sound ? "good" : "warn");
      } catch (error) {
        setTestResult("test_microphone_result", error.message, "warn");
      }
    }

    async function saveProfileMemory() {
      try {
        $("save_profile_memory").disabled = true;
        const result = await readJson("/api/memory/profile", {
          method: "POST",
          body: JSON.stringify({
            profile_markdown: $("profile_markdown").value
          })
        });
        populateMemory(result);
        setMemoryFeedback("Profile memory saved.", "good");
        setMessage("Profile memory saved.", "good");
      } catch (error) {
        setMemoryFeedback(error.message, "warn");
        setMessage(error.message, "warn");
      } finally {
        $("save_profile_memory").disabled = false;
      }
    }

    async function saveProfileBaseline() {
      try {
        $("save_profile_baseline").disabled = true;
        const result = await readJson("/api/memory/profile/baseline/save", {
          method: "POST",
          body: JSON.stringify({})
        });
        populateMemory(result);
        setMemoryFeedback("Profile baseline saved.", "good");
        setMessage("Profile baseline saved.", "good");
      } catch (error) {
        setMemoryFeedback(error.message, "warn");
        setMessage(error.message, "warn");
      } finally {
        $("save_profile_baseline").disabled = false;
      }
    }

    async function restoreProfileBaseline() {
      try {
        $("restore_profile_baseline").disabled = true;
        const result = await readJson("/api/memory/profile/baseline/restore", {
          method: "POST",
          body: JSON.stringify({})
        });
        populateMemory(result);
        setMemoryFeedback("Profile restored from baseline.", "good");
        setMessage("Profile restored from baseline.", "good");
      } catch (error) {
        setMemoryFeedback(error.message, "warn");
        setMessage(error.message, "warn");
      } finally {
        $("restore_profile_baseline").disabled = false;
      }
    }

    async function saveMemoryIndex() {
      try {
        $("save_memory_index").disabled = true;
        const result = await readJson("/api/memory/index", {
          method: "POST",
          body: JSON.stringify({})
        });
        populateMemory(result);
        setMemoryFeedback("Memory index regenerated.", "good");
        setMessage("Memory index regenerated.", "good");
      } catch (error) {
        setMemoryFeedback(error.message, "warn");
        setMessage(error.message, "warn");
      } finally {
        $("save_memory_index").disabled = false;
      }
    }

    function autoGrowPrompt() {
      const textarea = $("system_prompt");
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    }

    function autoGrowAdvanced() {
      const textarea = $("advanced_json");
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    }

    function autoGrowProfile() {
      const textarea = $("profile_markdown");
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    }

    function autoGrowMemoryIndex() {
      const textarea = $("memory_index_markdown");
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    }

    function showTab(name) {
      const panels = ["identity", "ai", "audio", "tools", "memory", "advanced"];
      for (const panel of panels) {
        const active = panel === name;
        $("panel_" + panel).classList.toggle("hidden", !active);
        $("tab_" + panel).classList.toggle("active", active);
      }
      if (name === "advanced") {
        requestAnimationFrame(autoGrowAdvanced);
      }
      if (name === "memory") {
        requestAnimationFrame(autoGrowProfile);
        requestAnimationFrame(autoGrowMemoryIndex);
      }
    }

    $("validate").addEventListener("click", validateConfig);
    $("apply").addEventListener("click", applyConfig);
    $("upload_wake_word_model").addEventListener("click", uploadWakeWordModel);
    $("test_speaker").addEventListener("click", testSpeaker);
    $("test_microphone").addEventListener("click", testMicrophone);
    $("system_prompt").addEventListener("input", autoGrowPrompt);
    $("advanced_json").addEventListener("input", autoGrowAdvanced);
    $("profile_markdown").addEventListener("input", autoGrowProfile);
    $("memory_index_markdown").addEventListener("input", autoGrowMemoryIndex);
    $("tab_identity").addEventListener("click", () => showTab("identity"));
    $("tab_ai").addEventListener("click", () => showTab("ai"));
    $("tab_audio").addEventListener("click", () => showTab("audio"));
    $("tab_advanced").addEventListener("click", () => showTab("advanced"));
    $("tab_tools").addEventListener("click", () => showTab("tools"));
    $("tab_memory").addEventListener("click", () => showTab("memory"));
    $("save_profile_memory").addEventListener("click", saveProfileMemory);
    $("save_profile_baseline").addEventListener("click", saveProfileBaseline);
    $("restore_profile_baseline").addEventListener("click", restoreProfileBaseline);
    $("save_memory_index").addEventListener("click", saveMemoryIndex);
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


class ConfigUIHandler(BaseHTTPRequestHandler):
    server_version = f"SnowmanConfigUI/{VERSION}"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not self._check_auth():
            return
        if parsed.path == "/":
            self._write_html(HTML_PAGE)
            return
        if parsed.path == "/assets/snowman_retro.svg":
            self._write_asset(ASSETS_DIR / "snowman_retro.svg", "image/svg+xml")
            return
        if parsed.path == "/api/config":
            self._write_json({"config": _config_payload_for_api(_load_config())})
            return
        if parsed.path == "/api/tools":
            self._write_json({"tools": _tool_payload_for_api(_load_config())})
            return
        if parsed.path == "/api/memory":
            self._write_json(_memory_payload_for_api(_load_config()))
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
        if parsed.path == "/api/wake-word/upload":
            try:
                upload_result = _store_wake_word_model(body)
            except RuntimeError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(upload_result)
            return

        if parsed.path == "/api/audio-test/speaker":
            try:
                result = _test_speaker(body)
            except RuntimeError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(result)
            return

        if parsed.path == "/api/audio-test/microphone":
            try:
                result = _test_microphone(body)
            except RuntimeError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(result)
            return
        if parsed.path == "/api/memory/profile":
            try:
                result = _update_profile_memory(_load_config(), body)
            except RuntimeError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(result)
            return
        if parsed.path == "/api/memory/profile/baseline/save":
            try:
                result = _save_profile_baseline(_load_config())
            except RuntimeError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(result)
            return
        if parsed.path == "/api/memory/profile/baseline/restore":
            try:
                result = _restore_profile_baseline(_load_config())
            except RuntimeError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(result)
            return
        if parsed.path == "/api/memory/index":
            self._write_json(_memory_payload_for_api(_load_config()))
            return

        merged = merge_config_values(_load_config(), body)
        if parsed.path == "/api/config/validate":
            errors = validate_config_values(merged)
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
            errors = validate_config_values(merged)
            if errors:
                self._write_json(
                    {"error": "\n".join(errors), "errors": errors},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                _apply_config(merged)
            except RuntimeError as exc:
                self.server.last_apply_message = str(exc)
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self.server.last_apply_message = "Configuration applied successfully."
            self._write_json(
                {
                    "message": self.server.last_apply_message,
                    "config": _config_payload_for_api(_load_config()),
                    "tools": _tool_payload_for_api(_load_config()),
                    "status": _status_payload(last_apply_message=self.server.last_apply_message),
                }
            )
            return
        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _check_auth(self) -> bool:
        password = _load_config().get("admin_password", "")
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

    def _write_asset(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._write_json({"error": "Asset not found"}, status=HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
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


def _load_config() -> dict[str, object]:
    return load_config_values(default_system_prompt=DEFAULT_SYSTEM_PROMPT)


def _config_payload_for_api(config_payload: dict[str, object]) -> dict[str, object]:
    payload = config_values_for_api(config_payload)
    payload["audio_input_options"] = _audio_input_options()
    payload["audio_output_options"] = _audio_output_options()
    advanced = payload.get("advanced", {})
    payload["memory_enabled"] = bool(advanced.get("memory_enabled", False)) if isinstance(advanced, dict) else False
    return payload


def _tool_payload_for_api(config_payload: dict[str, object]) -> list[dict[str, str]]:
    advanced = config_payload.get("advanced", {})
    memory_enabled = bool(advanced.get("memory_enabled", False)) if isinstance(advanced, dict) else False
    return [
        {
            "name": definition.name,
            "description": definition.description,
        }
        for definition in build_tool_definitions(memory_enabled=memory_enabled)
    ]


def _memory_store_for_config(config_payload: dict[str, object]) -> MemoryStore:
    advanced = config_payload.get("advanced", {})
    raw_dir = DEFAULT_MEMORY_DIR
    if isinstance(advanced, dict):
        raw_dir = str(advanced.get("memory_dir", raw_dir)).strip() or raw_dir
    base_dir = APP_DIR / raw_dir if not Path(raw_dir).is_absolute() else Path(raw_dir)
    return MemoryStore.from_path(str(base_dir))


def _memory_payload_for_api(config_payload: dict[str, object]) -> dict[str, object]:
    store = _memory_store_for_config(config_payload)
    store.ensure_initialized()
    advanced = config_payload.get("advanced", {})
    memory_enabled = bool(advanced.get("memory_enabled", False)) if isinstance(advanced, dict) else False
    return {
        "memory_enabled": memory_enabled,
        "memory_dir": str(store.paths.base_dir),
        "profile_path": str(store.paths.profile_path),
        "memory_index_path": str(store.paths.index_path),
        "baseline_path": str(store.paths.baseline_path),
        "baseline_exists": store.baseline_exists(),
        "profile_markdown": store.read_profile(),
        "memory_index_markdown": store.read_memory_index(),
    }


def _update_profile_memory(
    config_payload: dict[str, object],
    body: dict[str, object],
) -> dict[str, object]:
    profile_markdown = str(body.get("profile_markdown", ""))
    if not profile_markdown.strip():
        raise RuntimeError("profile_markdown is required.")
    store = _memory_store_for_config(config_payload)
    try:
        store.update_profile(profile_markdown)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    return _memory_payload_for_api(config_payload)


def _save_profile_baseline(config_payload: dict[str, object]) -> dict[str, object]:
    store = _memory_store_for_config(config_payload)
    store.save_current_as_baseline()
    return _memory_payload_for_api(config_payload)


def _restore_profile_baseline(config_payload: dict[str, object]) -> dict[str, object]:
    store = _memory_store_for_config(config_payload)
    store.restore_baseline()
    return _memory_payload_for_api(config_payload)


def _status_payload(
    *,
    config_payload: dict[str, object] | None = None,
    last_apply_message: str = "",
) -> dict[str, object]:
    current = config_payload or _load_config()
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
    paths = resolve_config_paths()
    temp_dir = paths.data_dir / ".tmp-config-ui"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_paths = ConfigPaths(
        data_dir=temp_dir,
        config_path=temp_dir / "config.json",
        secrets_path=temp_dir / "secrets.json",
        identity_path=temp_dir / "identity.md",
    )
    write_config_files(temp_paths, payload)
    script_path = APP_DIR / "scripts" / "apply_config.sh"
    result = subprocess.run(
        [
            str(script_path),
            "--config",
            str(temp_paths.config_path),
            "--secrets",
            str(temp_paths.secrets_path),
            "--identity",
            str(temp_paths.identity_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or "Failed to apply configuration")


def _audio_input_options() -> list[dict[str, str]]:
    options = [{"value": "-1", "label": "Auto"}]
    options.extend(list_input_devices())
    return options


def _audio_output_options() -> list[dict[str, str]]:
    options = [{"value": "auto", "label": "Auto"}]
    options.extend(list_playback_devices())
    return options


def _test_speaker(payload: dict[str, object]) -> dict[str, object]:
    merged = merge_config_values(_load_config(), payload)
    advanced = merged.get("advanced", {})
    if not isinstance(advanced, dict):
        advanced = {}
    playback_device = str(advanced.get("playback_device", "auto")).strip() or "auto"
    resolved_device = resolve_playback_device(playback_device)
    raw_cue_path = str(advanced.get("ready_cue_path", APP_DIR / "audio" / "ready_cue.wav")).strip()
    cue_path = str((APP_DIR / raw_cue_path).resolve()) if raw_cue_path and not Path(raw_cue_path).is_absolute() else raw_cue_path
    try:
        play_speaker_test(
            sample_rate=int(advanced.get("realtime_sample_rate", 24000)),
            playback_device=resolved_device,
            cue_path=cue_path,
            gain=float(merged.get("cue_output_gain", 0.5)),
        )
    except Exception as exc:
        raise RuntimeError(f"Speaker test failed: {exc}") from exc
    return {
        "message": f"Played a short test sound on {resolved_device or 'the default speaker output'}.",
        "playback_device": resolved_device or "default",
    }


def _test_microphone(payload: dict[str, object]) -> dict[str, object]:
    merged = merge_config_values(_load_config(), payload)
    advanced = merged.get("advanced", {})
    if not isinstance(advanced, dict):
        advanced = {}
    try:
        configured_index = int(advanced.get("audio_device_index", -1))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Microphone input selection is invalid.") from exc
    try:
        result = sample_microphone_level(
            device_index=resolve_input_device_index(configured_index),
            frame_length=int(advanced.get("input_frame_length", 512)),
            duration_seconds=1.5,
        )
    except Exception as exc:
        raise RuntimeError(f"Microphone test failed: {exc}") from exc
    return result


def _store_wake_word_model(payload: dict[str, object]) -> dict[str, object]:
    filename = str(payload.get("filename", "")).strip()
    content_base64 = str(payload.get("content_base64", "")).strip()
    if not filename or not filename.lower().endswith(".ppn"):
        raise RuntimeError("Wake word upload must be a .ppn file.")
    if not content_base64:
        raise RuntimeError("Wake word upload is missing file content.")

    safe_name = "".join(
        char for char in Path(filename).name if char.isalnum() or char in {"-", "_", "."}
    )
    if not safe_name.lower().endswith(".ppn"):
        raise RuntimeError("Wake word upload must keep a .ppn filename.")

    try:
        raw_bytes = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise RuntimeError("Wake word upload content is not valid base64.") from exc
    if not raw_bytes:
        raise RuntimeError("Wake word upload is empty.")

    wake_word_dir = resolve_config_paths().data_dir / "wake_words"
    wake_word_dir.mkdir(parents=True, exist_ok=True)
    target_path = wake_word_dir / safe_name
    target_path.write_bytes(raw_bytes)
    return {
        "custom_wake_keyword_path": str(target_path),
        "custom_wake_keyword_name": safe_name,
    }


if __name__ == "__main__":
    main()
