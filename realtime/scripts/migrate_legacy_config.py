#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REALTIME_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(REALTIME_DIR))

from snowman_realtime.config import DEFAULT_SYSTEM_PROMPT
from snowman_realtime.config_store import (
    config_updates_from_legacy_env,
    default_public_config,
    load_config_file,
    load_legacy_env_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--legacy-env-file")
    return parser.parse_args()


def load_legacy_secrets(path: Path) -> dict[str, str]:
    payload = load_legacy_env_file(path)
    secrets: dict[str, str] = {}
    if payload.get("OPENAI_API_KEY", "").strip():
        secrets["openai_api_key"] = payload["OPENAI_API_KEY"].strip()
    if payload.get("PORCUPINE_ACCESS_KEY", "").strip():
        secrets["porcupine_access_key"] = payload["PORCUPINE_ACCESS_KEY"].strip()
    if payload.get("ADMIN_PASSWORD", "").strip():
        secrets["admin_password"] = payload["ADMIN_PASSWORD"].strip()
    return secrets


def merge_config(current: dict[str, object], updates: dict[str, object]) -> dict[str, object]:
    defaults = default_public_config(default_system_prompt=DEFAULT_SYSTEM_PROMPT)
    if current:
        merged = dict(current)
    else:
        merged = dict(defaults)

    for key, value in updates.items():
        if key == "advanced" and isinstance(value, dict):
            existing_advanced = merged.get("advanced", {})
            if not isinstance(existing_advanced, dict) or not existing_advanced:
                existing_advanced = dict(defaults["advanced"])
            else:
                existing_advanced = dict(existing_advanced)
            for adv_key, adv_value in value.items():
                current_value = existing_advanced.get(adv_key)
                default_value = defaults["advanced"].get(adv_key)
                if current_value in {None, ""} or current_value == default_value:
                    existing_advanced[adv_key] = adv_value
            merged["advanced"] = existing_advanced
            continue

        current_value = merged.get(key)
        default_value = defaults.get(key)
        if current_value in {None, ""} or current_value == default_value:
            merged[key] = value

    return merged


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir).expanduser()
    config_path = data_dir / "config.json"
    secrets_path = data_dir / "secrets.json"
    legacy_path = data_dir / "secrets.env"
    legacy_env_path = (
        Path(args.legacy_env_file).expanduser()
        if args.legacy_env_file
        else REALTIME_DIR / ".env"
    )
    if not legacy_env_path.exists():
        backup_candidate = data_dir / "backups" / "realtime-config-legacy.env"
        if backup_candidate.exists():
            legacy_env_path = backup_candidate
    backups_dir = data_dir / "backups"

    data_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    if legacy_path.exists() and not secrets_path.exists():
        payload = load_legacy_secrets(legacy_path)
        write_json(secrets_path, payload)
        legacy_backup = backups_dir / "secrets-legacy.env"
        legacy_path.replace(legacy_backup)

    if legacy_env_path.exists():
        current_config = load_config_file(config_path) if config_path.exists() else {}
        updates = config_updates_from_legacy_env(load_legacy_env_file(legacy_env_path))
        merged_config = merge_config(current_config, updates)
        write_json(config_path, merged_config)
        legacy_env_backup = backups_dir / "realtime-config-legacy.env"
        if legacy_env_path != legacy_env_backup and legacy_env_backup.exists():
            legacy_env_backup.unlink()
        if legacy_env_path != legacy_env_backup:
            legacy_env_path.replace(legacy_env_backup)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
