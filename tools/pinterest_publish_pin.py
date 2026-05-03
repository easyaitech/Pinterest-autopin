#!/usr/bin/env python3
"""Agent-friendly single-pin Pinterest publishing entrypoint."""

from __future__ import annotations

import argparse
import json
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
PIN_URL_RE = re.compile(r"https?://(?:www\.)?pinterest\.com/pin/[^\s\"'<>]+")
TEXT_FIELDS = ("image", "title", "board", "link", "description", "altText")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or publish a single Pinterest pin with structured JSON output."
    )
    parser.add_argument("--input", help="Path to the JSON request file.")
    parser.add_argument(
        "--mode",
        choices=("validate", "test", "final"),
        default="validate",
        help="validate only, fill without publishing, or publish for real.",
    )
    parser.add_argument("--image", help="Absolute path to the image file.")
    parser.add_argument("--title", help="Pin title.")
    parser.add_argument("--board", help="Pinterest board name.")
    parser.add_argument("--link", help="Destination link.")
    parser.add_argument("--description", help="Pin description.")
    parser.add_argument("--alt-text", dest="alt_text", help="Alt text.")
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


def normalize_payload(file_payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    payload = dict(file_payload)

    overrides = {
        "image": args.image,
        "title": args.title,
        "board": args.board,
        "link": args.link,
        "description": args.description,
        "altText": args.alt_text,
    }
    for key, value in overrides.items():
        if value is not None:
            payload[key] = value

    alt_text = payload.get("altText")
    if alt_text is None:
        alt_text = payload.get("alt_text")
    if alt_text is None:
        alt_text = payload.get("alt-text")

    normalized = {
        "image": payload.get("image", ""),
        "title": payload.get("title", ""),
        "board": payload.get("board", ""),
        "link": payload.get("link", ""),
        "description": payload.get("description", ""),
        "altText": "" if alt_text is None else alt_text,
    }
    return normalized


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


def validate_payload(payload: dict[str, Any], checks: dict[str, Any], mode: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for field in TEXT_FIELDS:
        if not isinstance(payload[field], str):
            errors.append(f"{field} must be a string")

    if errors:
        return errors, warnings

    image_path = Path(payload["image"])
    if not payload["image"].strip():
        errors.append("image is required")
    elif not image_path.is_absolute():
        errors.append(f"image must be an absolute path: {payload['image']}")
    elif not image_path.exists():
        errors.append(f"image does not exist: {payload['image']}")

    if not payload["title"].strip():
        errors.append("title is required")

    if payload["link"].strip():
        parsed_link = urlparse(payload["link"])
        if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
            errors.append(f"link must be an absolute http(s) URL: {payload['link']}")

    if not checks["nodeScriptExists"]:
        errors.append(f"publish script not found: {NODE_SCRIPT}")

    if not checks["nodePath"]:
        errors.append("node is not installed or not on PATH")

    if not checks["sipsPath"]:
        warnings.append("sips not found; image compression will fail on macOS-only path")

    if not payload["board"].strip():
        if mode in {"test", "final"}:
            errors.append("board is required in test/final mode to avoid posting to the wrong board")
        else:
            warnings.append("board is empty; validate mode allows this, but real execution requires it")

    if mode in {"test", "final"}:
        if not checks["playwrightInstalled"]:
            errors.append("playwright dependency is not installed; run npm install first")
        if not checks["chromeCdp"]["reachable"]:
            errors.append("Chrome CDP is not reachable at http://127.0.0.1:9222/json/version")

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
        payload = normalize_payload(file_payload, args)
    except Exception as exc:  # noqa: BLE001
        return print_json(
            {
                "ok": False,
                "mode": args.mode,
                "errors": [f"failed to load input: {exc}"],
            },
            1,
        )

    checks = build_checks()
    errors, warnings = validate_payload(payload, checks, args.mode)
    response: dict[str, Any] = {
        "ok": not errors,
        "mode": args.mode,
        "payload": payload,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }

    if args.mode == "validate" or errors:
        return print_json(response, 0 if not errors else 1)

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
        response["errors"].append("publish command failed")
    return print_json(response, 0 if execution["ok"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
