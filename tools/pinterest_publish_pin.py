#!/usr/bin/env python3
"""Agent-friendly single-pin Pinterest publishing entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_SCRIPT = REPO_ROOT / "publish_playwright.js"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PIN_URL_RE = re.compile(r"https?://(?:[a-z0-9-]+\.)?pinterest\.com/pin/[^\s\"'<>]+")
TEXT_FIELDS = (
    "title",
    "board",
    "link",
    "description",
    "chromeProfile",
    "creationUrl",
)
PROFILE_KEYS = ("chromeProfile", "chrome_profile", "chrome-profile")
CREATION_URL_KEYS = ("creationUrl", "creation_url", "creation-url")
PROFILE_ENV_VAR = "PINTEREST_AUTOPIN_CHROME_PROFILE"
CREATION_URL_ENV_VAR = "PINTEREST_AUTOPIN_CREATION_URL"
DEFAULT_CREATION_URL = "https://www.pinterest.com/pin-creation-tool/"
CONFIG_DIR = Path.home() / ".pinterest-autopin"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_CHROME_PROFILE = CONFIG_DIR / "chrome-profile"
CHROME_PROFILE_DISPLAY_NAME = "Pinterest AutoPin"
CHROME_PROFILE_INTERNAL_DIR = "Default"
CHROME_PROFILE_LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or publish a single Pinterest pin with structured JSON output."
    )
    parser.add_argument("--input", help="Path to the JSON request file.")
    parser.add_argument(
        "--mode",
        choices=("validate", "test", "final", "check-login"),
        default="validate",
        help="validate only, check login, fill without publishing, or publish for real.",
    )
    parser.add_argument("--image", help="Absolute path to the image file.")
    parser.add_argument("--title", help="Pin title.")
    parser.add_argument("--board", help="Pinterest board name.")
    parser.add_argument("--link", help="Destination link.")
    parser.add_argument("--description", help="Pin description.")
    parser.add_argument("--alt-text", dest="alt_text", help="Alt text.")
    parser.add_argument(
        "--chrome-profile",
        dest="chrome_profile",
        help="Absolute path to a dedicated Chrome user data directory.",
    )
    parser.add_argument(
        "--creation-url",
        dest="creation_url",
        help="Pinterest Pin creation URL, for example https://jp.pinterest.com/pin-creation-tool/.",
    )
    parser.add_argument(
        "--print-chrome-profile",
        action="store_true",
        help="Print the resolved Chrome profile path as JSON and exit.",
    )
    parser.add_argument(
        "--init-chrome-profile",
        action="store_true",
        help="Create the resolved Chrome profile directory and save it for future runs.",
    )
    parser.add_argument(
        "--no-default-chrome-profile",
        action="store_true",
        help="Do not infer a default Chrome profile; use legacy CDP if no profile is provided.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Execution timeout in seconds for test/final modes.",
    )
    return parser.parse_args()


def load_input_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


def expand_profile_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    if not cleaned:
        return ""
    return str(Path(os.path.expandvars(cleaned)).expanduser())


def read_config_chrome_profile() -> Any:
    if not CONFIG_PATH.exists():
        return ""
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in PROFILE_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return ""


def resolve_chrome_profile(payload: dict[str, Any], args: argparse.Namespace) -> tuple[Any, str]:
    if args.chrome_profile is not None:
        return expand_profile_path(args.chrome_profile), "cli"

    for key in PROFILE_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return expand_profile_path(value), f"input:{key}"

    env_value = os.environ.get(PROFILE_ENV_VAR, "").strip()
    if env_value:
        return expand_profile_path(env_value), f"env:{PROFILE_ENV_VAR}"

    if getattr(args, "no_default_chrome_profile", False):
        return "", "none"

    config_value = read_config_chrome_profile()
    if config_value not in (None, ""):
        return expand_profile_path(config_value), f"config:{CONFIG_PATH}"

    return str(DEFAULT_CHROME_PROFILE), "default"


def resolve_creation_url(payload: dict[str, Any], args: argparse.Namespace) -> Any:
    if getattr(args, "creation_url", None) is not None:
        return args.creation_url

    for key in CREATION_URL_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return value

    env_value = os.environ.get(CREATION_URL_ENV_VAR, "").strip()
    if env_value:
        return env_value

    return DEFAULT_CREATION_URL


def chrome_profile_metadata(source: str) -> dict[str, str]:
    return {
        "source": source,
        "envVar": PROFILE_ENV_VAR,
        "configPath": str(CONFIG_PATH),
        "defaultPath": str(DEFAULT_CHROME_PROFILE),
        "displayName": CHROME_PROFILE_DISPLAY_NAME,
    }


def normalize_images(payload: dict[str, Any], args: argparse.Namespace) -> list[dict[str, str]]:
    """Build the images array from either ``images`` key or flat ``image``/``altText``."""
    images_raw = payload.get("images")
    if isinstance(images_raw, list) and images_raw:
        result: list[dict[str, str]] = []
        for item in images_raw:
            if not isinstance(item, dict):
                continue
            result.append({
                "path": str(item.get("path") or ""),
                "altText": str(item.get("altText") or item.get("alt_text") or ""),
            })
        return result

    image = args.image if args.image is not None else str(payload.get("image") or "")
    alt_text = args.alt_text
    if alt_text is None:
        alt_text = payload.get("altText") or payload.get("alt_text") or payload.get("alt-text") or ""
    if image:
        return [{"path": image, "altText": str(alt_text)}]
    return []


def normalize_payload_with_meta(
    file_payload: dict[str, Any], args: argparse.Namespace
) -> tuple[dict[str, Any], dict[str, str]]:
    payload = dict(file_payload)

    overrides = {
        "title": args.title,
        "board": args.board,
        "link": args.link,
        "description": args.description,
        "chromeProfile": args.chrome_profile,
        "creationUrl": getattr(args, "creation_url", None),
    }
    for key, value in overrides.items():
        if value is not None:
            payload[key] = value

    chrome_profile, chrome_profile_source = resolve_chrome_profile(payload, args)
    creation_url = resolve_creation_url(payload, args)
    images = normalize_images(payload, args)

    normalized = {
        "images": images,
        "title": payload.get("title", ""),
        "board": payload.get("board", ""),
        "link": payload.get("link", ""),
        "description": payload.get("description", ""),
        "chromeProfile": "" if chrome_profile is None else chrome_profile,
        "creationUrl": "" if creation_url is None else creation_url,
    }
    return normalized, chrome_profile_metadata(chrome_profile_source)


def normalize_payload(file_payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    payload, _profile_meta = normalize_payload_with_meta(file_payload, args)
    return payload


def cdp_status() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2) as response:
            payload = json.load(response)
        return {
            "reachable": True,
            "webSocketDebuggerUrl": payload.get("webSocketDebuggerUrl", ""),
            "browser": payload.get("Browser", ""),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {
            "reachable": False,
            "webSocketDebuggerUrl": "",
            "browser": "",
        }


def build_checks() -> dict[str, Any]:
    node_path = shutil.which("node")
    sips_path = shutil.which("sips")
    node_modules_playwright = REPO_ROOT / "node_modules" / "playwright"

    return {
        "repoRoot": str(REPO_ROOT),
        "nodeScriptExists": NODE_SCRIPT.exists(),
        "nodePath": node_path or "",
        "sipsPath": sips_path or "",
        "playwrightInstalled": node_modules_playwright.exists(),
        "chromeCdp": cdp_status(),
    }


def validate_chrome_profile_path(
    chrome_profile: Any, require_profile: bool = False
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(chrome_profile, str):
        errors.append("chromeProfile must be a string")
        return errors, warnings

    chrome_profile = chrome_profile.strip()
    if not chrome_profile:
        if require_profile:
            errors.append("chromeProfile is empty")
        return errors, warnings

    chrome_profile_path = Path(chrome_profile)
    if not chrome_profile_path.is_absolute():
        errors.append(f"chromeProfile must be an absolute path: {chrome_profile}")
    elif chrome_profile_path.exists() and not chrome_profile_path.is_dir():
        errors.append(f"chromeProfile must be a directory: {chrome_profile}")
    elif not chrome_profile_path.exists():
        warnings.append(
            "chromeProfile directory does not exist yet; it will be created, "
            "but Pinterest login may be required"
        )

    return errors, warnings


def validate_creation_url(creation_url: str) -> list[str]:
    parsed = urlparse(creation_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return [f"creationUrl must be an absolute http(s) URL: {creation_url}"]
    host = (parsed.hostname or "").lower()
    if host != "pinterest.com" and not host.endswith(".pinterest.com"):
        return [f"creationUrl must be a Pinterest URL: {creation_url}"]
    if "/pin-creation-tool" not in parsed.path and "/pin-builder" not in parsed.path:
        return [f"creationUrl must point to a Pinterest creation page: {creation_url}"]
    return []


def validate_payload(payload: dict[str, Any], checks: dict[str, Any], mode: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for field in TEXT_FIELDS:
        if not isinstance(payload.get(field, ""), str):
            errors.append(f"{field} must be a string")

    if errors:
        return errors, warnings

    if mode != "check-login":
        images = payload.get("images", [])
        if not images:
            errors.append("images array is required (or provide flat image field)")
        else:
            for i, img in enumerate(images):
                img_path = img.get("path", "")
                if not img_path:
                    errors.append(f"images[{i}].path is required")
                elif not Path(img_path).is_absolute():
                    errors.append(f"images[{i}].path must be an absolute path: {img_path}")
                elif not Path(img_path).exists():
                    errors.append(f"images[{i}].path does not exist: {img_path}")
            if len(images) > 5:
                errors.append(f"images array has {len(images)} elements; Pinterest carousel limit is 5")

        if not payload["title"].strip():
            errors.append("title is required")

    if payload["link"].strip():
        parsed_link = urlparse(payload["link"])
        if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
            errors.append(f"link must be an absolute http(s) URL: {payload['link']}")

    errors.extend(validate_creation_url(payload["creationUrl"].strip()))

    chrome_profile = payload["chromeProfile"].strip()
    profile_errors, profile_warnings = validate_chrome_profile_path(chrome_profile)
    errors.extend(profile_errors)
    warnings.extend(profile_warnings)

    if not checks["nodeScriptExists"]:
        errors.append(f"publish script not found: {NODE_SCRIPT}")

    if not checks["nodePath"]:
        errors.append("node is not installed or not on PATH")

    if not checks["sipsPath"]:
        warnings.append("sips not found; image compression will fail on macOS-only path")

    if mode != "check-login" and not payload["board"].strip():
        if mode in {"test", "final"}:
            errors.append("board is required in test/final mode to avoid posting to the wrong board")
        else:
            warnings.append("board is empty; validate mode allows this, but real execution requires it")

    if mode in {"test", "final", "check-login"}:
        if not checks["playwrightInstalled"]:
            errors.append("playwright dependency is not installed; run npm install first")
        if not chrome_profile and not checks["chromeCdp"]["reachable"]:
            errors.append(
                "chromeProfile is required in test/final/check-login mode unless an existing "
                "Chrome CDP session is reachable"
            )

    return errors, warnings


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def find_pin_url(result_payload: dict[str, Any] | None, stdout: str) -> str:
    if result_payload and result_payload.get("finalUrl"):
        return str(result_payload["finalUrl"])
    match = PIN_URL_RE.search(stdout)
    return match.group(0) if match else ""


def execution_error_message(execution: dict[str, Any]) -> str:
    result = execution.get("result")
    if isinstance(result, dict):
        error = str(result.get("error") or "").strip()
        if error:
            return error
    return "publish command failed"


def save_chrome_profile_config(chrome_profile: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config_payload: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                config_payload = existing
        except (OSError, json.JSONDecodeError):
            config_payload = {}
    config_payload["chromeProfile"] = chrome_profile
    config_payload["chromeProfileName"] = CHROME_PROFILE_DISPLAY_NAME
    CONFIG_PATH.write_text(
        json.dumps(config_payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def read_chrome_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to read Chrome profile metadata {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Chrome profile metadata must be a JSON object: {path}")
    return payload


def write_chrome_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    temp_path.replace(path)


def ensure_nested_object(payload: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = payload.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(
            f"Chrome profile metadata field must be an object: {path}::{key}"
        )
    return value


def ensure_chrome_profile_display_name(chrome_profile: str) -> None:
    profile_root = Path(chrome_profile)
    profile_root.mkdir(parents=True, exist_ok=True)

    local_state_path = profile_root / "Local State"
    local_state = read_chrome_json_object(local_state_path)
    profile_state = ensure_nested_object(local_state, "profile", local_state_path)
    info_cache = ensure_nested_object(profile_state, "info_cache", local_state_path)
    default_cache = ensure_nested_object(
        info_cache, CHROME_PROFILE_INTERNAL_DIR, local_state_path
    )
    default_cache["name"] = CHROME_PROFILE_DISPLAY_NAME
    default_cache["shortcut_name"] = CHROME_PROFILE_DISPLAY_NAME
    default_cache["is_using_default_name"] = False
    profile_state.setdefault("last_used", CHROME_PROFILE_INTERNAL_DIR)
    profile_state.setdefault("last_active_profiles", [CHROME_PROFILE_INTERNAL_DIR])
    write_chrome_json_object(local_state_path, local_state)

    preferences_path = profile_root / CHROME_PROFILE_INTERNAL_DIR / "Preferences"
    preferences = read_chrome_json_object(preferences_path)
    preferences_profile = ensure_nested_object(preferences, "profile", preferences_path)
    preferences_profile["name"] = CHROME_PROFILE_DISPLAY_NAME
    preferences_profile["using_default_name"] = False
    write_chrome_json_object(preferences_path, preferences)


def chrome_profile_appears_open(chrome_profile: str) -> bool:
    profile_root = Path(chrome_profile)
    return any(os.path.lexists(profile_root / name) for name in CHROME_PROFILE_LOCK_FILES)


def init_chrome_profile(chrome_profile: str) -> None:
    Path(chrome_profile).mkdir(parents=True, exist_ok=True)
    if chrome_profile_appears_open(chrome_profile):
        raise ValueError(
            "Chrome profile appears to be open; close the dedicated Pinterest Chrome "
            "window before refreshing the display name"
        )
    ensure_chrome_profile_display_name(chrome_profile)
    save_chrome_profile_config(chrome_profile)


def run_publish(payload: dict[str, Any], mode: str, timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pinterest-publish-") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "request.json"
        result_path = temp_path / "result.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

        command = [
            "node",
            str(NODE_SCRIPT),
            "--input",
            str(input_path),
            "--result-json",
            str(result_path),
        ]
        if payload["chromeProfile"]:
            command.extend(["--chrome-profile", payload["chromeProfile"]])
        if mode == "check-login":
            command.append("--check-login")
        else:
            command.append("--final" if mode == "final" else "--test")

        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        stdout = strip_ansi(completed.stdout)
        stderr = strip_ansi(completed.stderr)

        result_payload: dict[str, Any] | None = None
        if result_path.exists():
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))

        ok = completed.returncode == 0 and bool(result_payload and result_payload.get("ok"))
        return {
            "ok": ok,
            "mode": mode,
            "command": command,
            "exitCode": completed.returncode,
            "pinUrl": find_pin_url(result_payload, stdout),
            "result": result_payload,
            "stdoutTail": tail(stdout),
            "stderrTail": tail(stderr),
        }


def print_json(payload: dict[str, Any], exit_code: int) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return exit_code


def main() -> int:
    args = parse_args()

    try:
        file_payload = load_input_file(args.input)
        payload, profile_meta = normalize_payload_with_meta(file_payload, args)
    except Exception as exc:  # noqa: BLE001
        return print_json(
            {
                "ok": False,
                "mode": args.mode,
                "errors": [f"failed to load input: {exc}"],
            },
            1,
        )

    if args.print_chrome_profile or args.init_chrome_profile:
        profile_errors, profile_warnings = validate_chrome_profile_path(
            payload["chromeProfile"], require_profile=args.init_chrome_profile
        )
        response: dict[str, Any] = {
            "ok": not profile_errors,
            "chromeProfile": payload["chromeProfile"],
            "chromeProfileName": CHROME_PROFILE_DISPLAY_NAME,
            "chromeProfileSource": profile_meta["source"],
            "errors": profile_errors,
            "warnings": profile_warnings,
            "profile": profile_meta,
        }
        if profile_errors:
            return print_json(response, 1)
        if args.init_chrome_profile:
            try:
                init_chrome_profile(payload["chromeProfile"])
                response["created"] = True
                response["configSaved"] = True
            except Exception as exc:  # noqa: BLE001
                response["ok"] = False
                response["created"] = False
                response["configSaved"] = False
                response["errors"].append(f"failed to initialize chromeProfile: {exc}")
                return print_json(response, 1)
        return print_json(response, 0)

    checks = build_checks()
    errors, warnings = validate_payload(payload, checks, args.mode)
    response: dict[str, Any] = {
        "ok": not errors,
        "mode": args.mode,
        "payload": payload,
        "profile": profile_meta,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }

    if args.mode == "validate" or errors:
        return print_json(response, 0 if not errors else 1)

    if payload["chromeProfile"] and chrome_profile_appears_open(payload["chromeProfile"]):
        response["warnings"].append(
            "Chrome profile appears to be open; skipped display name refresh"
        )
    elif payload["chromeProfile"]:
        try:
            ensure_chrome_profile_display_name(payload["chromeProfile"])
        except Exception as exc:  # noqa: BLE001
            response["warnings"].append(f"failed to apply Chrome profile display name: {exc}")

    try:
        execution = run_publish(payload, args.mode, args.timeout)
    except subprocess.TimeoutExpired:
        response["ok"] = False
        response["errors"].append(f"publish timed out after {args.timeout} seconds")
        return print_json(response, 1)
    except Exception as exc:  # noqa: BLE001
        response["ok"] = False
        response["errors"].append(f"publish failed before completion: {exc}")
        return print_json(response, 1)

    response.update(execution)
    if not execution["ok"]:
        response["errors"].append(execution_error_message(execution))
    return print_json(response, 0 if execution["ok"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
