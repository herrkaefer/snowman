#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REALTIME_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(REALTIME_DIR))

from snowman_realtime.config import DEFAULT_SYSTEM_PROMPT
from snowman_realtime.config_store import (
    DEFAULT_ADVANCED_CONFIG,
    LEGACY_BASIC_ENV_TO_CONFIG_KEY,
    LEGACY_SECRET_ENV_TO_CONFIG_KEY,
    load_config_file,
    load_legacy_env_file,
    load_secrets_file,
    materialize_config_values,
)


@dataclass(frozen=True)
class ComparisonResult:
    env_key: str
    current_key: str
    matches: bool
    expected: object
    actual: object
    note: str = ""
    secret: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare migrated config.json/secrets.json values against a legacy realtime .env file."
    )
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--legacy-env", required=True, help="Path to legacy realtime .env")
    parser.add_argument("--secrets", help="Path to secrets.json")
    return parser.parse_args()


def compare_store_to_legacy_env(
    *,
    config_payload: dict[str, object],
    secrets_payload: dict[str, str],
    legacy_env: dict[str, str],
) -> list[ComparisonResult]:
    current = materialize_config_values(
        config_payload=config_payload,
        secret_payload=secrets_payload,
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
    )
    results: list[ComparisonResult] = []

    for env_key, current_key in LEGACY_BASIC_ENV_TO_CONFIG_KEY.items():
        if env_key not in legacy_env:
            continue
        expected = legacy_env[env_key]
        actual = current.get(current_key, "")
        matches = str(actual) == expected
        note = ""
        if env_key == "CUSTOM_WAKE_KEYWORD_PATH":
            matches, note = _compare_wake_word_path(expected, actual)
        results.append(
            ComparisonResult(
                env_key=env_key,
                current_key=current_key,
                matches=matches,
                expected=expected,
                actual=actual,
                note=note,
            )
        )

    for env_key, current_key in LEGACY_SECRET_ENV_TO_CONFIG_KEY.items():
        if env_key not in legacy_env:
            continue
        expected = legacy_env[env_key]
        actual = str(current.get(current_key, ""))
        results.append(
            ComparisonResult(
                env_key=env_key,
                current_key=current_key,
                matches=actual == expected,
                expected=expected,
                actual=actual,
                secret=True,
            )
        )

    for advanced_key, default_value in DEFAULT_ADVANCED_CONFIG.items():
        env_key = advanced_key.upper()
        if env_key not in legacy_env:
            continue
        expected = _coerce_env_value(legacy_env[env_key], default_value)
        actual = current["advanced"].get(advanced_key)
        results.append(
            ComparisonResult(
                env_key=env_key,
                current_key=f"advanced.{advanced_key}",
                matches=actual == expected,
                expected=expected,
                actual=actual,
            )
        )

    if "SESSION_WINDOW_ENABLED" in legacy_env:
        expected = _parse_bool(legacy_env["SESSION_WINDOW_ENABLED"])
        actual = True
        results.append(
            ComparisonResult(
                env_key="SESSION_WINDOW_ENABLED",
                current_key="derived.session_window_enabled",
                matches=actual == expected,
                expected=expected,
                actual=actual,
                note="Realtime now always runs in multi-turn mode.",
            )
        )

    return results


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser()
    secrets_path = (
        Path(args.secrets).expanduser()
        if args.secrets
        else config_path.with_name("secrets.json")
    )
    legacy_env_path = Path(args.legacy_env).expanduser()

    config_payload = load_config_file(config_path)
    secrets_payload = load_secrets_file(secrets_path) if secrets_path.exists() else {}
    legacy_env = load_legacy_env_file(legacy_env_path)
    results = compare_store_to_legacy_env(
        config_payload=config_payload,
        secrets_payload=secrets_payload,
        legacy_env=legacy_env,
    )

    mismatches = [result for result in results if not result.matches]
    for result in results:
        status = "OK" if result.matches else "MISMATCH"
        suffix = f" ({result.note})" if result.note else ""
        print(
            f"{status:<9} {result.env_key:<35} -> {result.current_key:<32} "
            f"expected={_display_value(result.expected, secret=result.secret)} "
            f"actual={_display_value(result.actual, secret=result.secret)}{suffix}"
        )

    print()
    print(f"Compared {len(results)} mapped values.")
    if mismatches:
        print(f"Found {len(mismatches)} mismatches.", file=sys.stderr)
        return 1
    print("All mapped values match.")
    return 0


def _display_value(value: object, *, secret: bool) -> str:
    if isinstance(value, str):
        return json.dumps(_mask_if_secret(value) if secret else value)
    return repr(value)


def _mask_if_secret(value: str) -> str:
    if len(value) > 8:
        return f"{value[:4]}...{value[-4:]}"
    return value


def _compare_wake_word_path(expected: object, actual: object) -> tuple[bool, str]:
    expected_str = str(expected)
    actual_str = str(actual)
    if actual_str == expected_str:
        return True, ""
    if Path(actual_str).name == Path(expected_str).name:
        return True, "Matched by wake word filename."
    return False, ""


def _coerce_env_value(raw_value: str, default_value: object) -> object:
    if isinstance(default_value, bool):
        return _parse_bool(raw_value)
    if isinstance(default_value, int):
        return int(raw_value)
    if isinstance(default_value, float):
        return float(raw_value)
    return raw_value


def _parse_bool(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
