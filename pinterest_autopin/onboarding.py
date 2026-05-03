"""Guided readiness checks for Hermes-based Pinterest AutoPin setup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .worker import FeishuPinterestWorker
from .worker_config import ConfigError, WorkerConfig, load_worker_config, validate_worker_config


REPO_ROOT = Path(__file__).resolve().parents[1]
PINTEREST_CLI = REPO_ROOT / "tools" / "pinterest_publish_pin.py"
DEFAULT_CONFIG = REPO_ROOT / ".gstack" / "feishu-worker-config.json"

LARK_REQUIRED_SCOPES = (
    "base:app:read",
    "base:table:read",
    "base:field:read",
    "base:record:read",
    "base:record:create",
    "base:record:update",
    "docs:document.media:upload",
    "drive:file:download",
    "wiki:node:read",
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], Optional[str]]


def run_onboarding(
    *,
    config_path: str | Path | None = None,
    local_dev: bool = False,
    chrome_profile: str = "",
    check_pinterest_login: bool = True,
    publish_singleton_confirmed: bool = False,
    target: str = "publish",
    env: Mapping[str, str] | None = None,
    command_runner: CommandRunner | None = None,
    which: Which | None = None,
    cdp_reachable: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    runtime_env = dict(env or os.environ)
    run = command_runner or subprocess.run
    which_bin = which or shutil.which
    check_cdp = cdp_reachable or _chrome_cdp_reachable

    steps: list[dict[str, Any]] = []
    resolved_config = Path(config_path) if config_path else DEFAULT_CONFIG
    config: WorkerConfig | None = None

    node_ok = bool(which_bin("node"))
    playwright_ok = (REPO_ROOT / "node_modules" / "playwright").exists()
    steps.append(
        _step(
            "install_dependencies",
            "Install project dependencies",
            "complete" if node_ok and playwright_ok else "action_required",
            "Node.js and Playwright are available." if node_ok and playwright_ok else "Run npm install in the repo.",
            agent_action="npm install",
            blocking=True,
        )
    )

    hermes_ok = local_dev or bool(_first_env(runtime_env, ("HERMES_RUN_ID", "HERMES_AGENT_RUN_ID", "RUN_ID"))) and bool(
        _first_env(runtime_env, ("HERMES_AGENT_ID", "AGENT_ID"))
    ) and bool(_first_env(runtime_env, ("HERMES_JOB_ID", "HERMES_SCHEDULE_ID", "JOB_ID")))
    steps.append(
        _step(
            "hermes_identity",
            "Run inside Hermes",
            "complete" if hermes_ok else "action_required",
            (
                "Hermes run identity is present."
                if hermes_ok and not local_dev
                else "Local setup mode is enabled."
                if local_dev
                else "Run this task inside Hermes, or pass --local-dev for setup-only checks."
            ),
            user_action="Start the onboarding task from Hermes, or use --local-dev for local testing.",
            blocking=True,
        )
    )

    config_exists = resolved_config.exists()
    if config_exists:
        try:
            config = load_worker_config(resolved_config)
            config_errors = validate_worker_config(config)
        except (OSError, json.JSONDecodeError, ConfigError) as exc:
            config_errors = [str(exc)]
    else:
        config_errors = [f"config file not found: {resolved_config}"]

    steps.append(
        _step(
            "feishu_config",
            "Create local Feishu worker config",
            "complete" if config_exists and not config_errors else "action_required",
            (
                "Local Feishu config is present and structurally valid."
                if config_exists and not config_errors
                else "Create .gstack/feishu-worker-config.json from the user's Base link."
            ),
            user_action="Send the Feishu Base/wiki link and approve schema creation when prompted.",
            agent_action="Resolve the Base, create missing tables/fields, and write .gstack/feishu-worker-config.json.",
            blocking=True,
            details={"configPath": str(resolved_config), "errors": config_errors[:5]},
        )
    )

    feishu_cli = config.feishu_cli if config else "lark-cli"
    feishu_cli_path = which_bin(feishu_cli)
    steps.append(
        _step(
            "feishu_cli",
            "Install Feishu/Lark CLI",
            "complete" if feishu_cli_path else "action_required",
            f"Feishu CLI found: {Path(feishu_cli_path).name}" if feishu_cli_path else f"Install {feishu_cli}.",
            user_action="Install lark-cli and log in locally.",
            blocking=True,
        )
    )

    if feishu_cli_path and _config_flavor(config) == "lark":
        scope_check = _check_lark_scopes(feishu_cli, LARK_REQUIRED_SCOPES, run)
        missing = scope_check.get("missing", [])
        steps.append(
            _step(
                "feishu_auth",
                "Authorize Feishu scopes",
                "complete" if not missing and scope_check.get("ok") else "action_required",
                (
                    "Required Feishu scopes are authorized."
                    if not missing and scope_check.get("ok")
                    else "Authorize the missing Feishu scopes."
                ),
                user_action=(
                    f'lark-cli auth login --scope "{" ".join(missing)}"'
                    if missing
                    else "Run lark-cli auth login if the CLI is not authenticated."
                ),
                blocking=True,
                details={"missingScopes": missing},
            )
        )

    if config and hermes_ok and feishu_cli_path and not config_errors:
        try:
            doctor = FeishuPinterestWorker.from_config(
                config,
                local_dev=local_dev,
                chrome_profile=chrome_profile,
            ).doctor()
            doctor_errors = list(doctor.errors)
        except Exception as exc:  # noqa: BLE001
            doctor_errors = [str(exc)]
    else:
        doctor_errors = ["doctor skipped until Hermes identity, Feishu CLI, and config are ready"]
    steps.append(
        _step(
            "feishu_doctor",
            "Verify Feishu tables and runtime lock",
            "complete" if not doctor_errors else "action_required",
            "Feishu doctor passed." if not doctor_errors else "Run doctor after config and auth are ready.",
            agent_action=f"python3 tools/feishu_pinterest_worker.py doctor --config {resolved_config}",
            blocking=True,
            details={"errors": doctor_errors[:5]},
        )
    )

    profile = _print_chrome_profile(run, chrome_profile)
    profile_path = profile.get("chromeProfile", "")
    profile_ok = bool(profile.get("ok")) and bool(profile_path)
    steps.append(
        _step(
            "pinterest_profile",
            "Initialize dedicated Pinterest Chrome profile",
            "complete" if profile_ok and Path(profile_path).exists() else "action_required",
            (
                "Dedicated Pinterest Chrome profile exists."
                if profile_ok and Path(profile_path).exists()
                else "Initialize the dedicated Chrome profile before login."
            ),
            user_action="Let the agent initialize the profile, then sign in to Pinterest in that Chrome window.",
            agent_action="python3 tools/pinterest_publish_pin.py --init-chrome-profile",
            blocking=True,
            details={"profileSource": profile.get("chromeProfileSource", ""), "profileReady": bool(Path(profile_path).exists())},
        )
    )

    pinterest_login = (
        _check_pinterest_login(run, check_cdp)
        if check_pinterest_login
        else {"ok": False, "skipped": True, "reason": "Skipped by --skip-pinterest-login-check"}
    )
    steps.append(
        _step(
            "pinterest_login",
            "Confirm Pinterest login",
            "complete" if pinterest_login.get("ok") else "action_required",
            (
                "Pinterest login check passed."
                if pinterest_login.get("ok")
                else "Sign in to Pinterest in the dedicated Chrome profile, then rerun onboarding."
            ),
            user_action="Open the dedicated Chrome profile, sign in to Pinterest, and keep that profile available to Hermes.",
            agent_action="python3 tools/pinterest_publish_pin.py --mode check-login --no-default-chrome-profile",
            blocking=True,
            details={
                "checked": not pinterest_login.get("skipped", False),
                "reason": pinterest_login.get("reason", ""),
            },
        )
    )

    publish_lock_ready = publish_singleton_confirmed or _config_flavor(config) == "bitable"
    steps.append(
        _step(
            "publish_singleton",
            "Protect the shared Pinterest profile",
            "complete" if publish_lock_ready else "action_required",
            (
                "Publish concurrency is guarded."
                if publish_lock_ready
                else "Official lark-cli cannot do atomic compare-update; configure Hermes to run publish as a singleton or use an atomic lock wrapper."
            ),
            user_action="Configure the Hermes publish schedule with max concurrency 1, then pass --publish-singleton-confirmed.",
            blocking=True,
        )
    )

    ready_for_prepare = _all_complete(steps, ("install_dependencies", "hermes_identity", "feishu_config", "feishu_cli", "feishu_auth", "feishu_doctor"))
    ready_for_publish = ready_for_prepare and _all_complete(steps, ("pinterest_profile", "pinterest_login", "publish_singleton"))

    target_ok = ready_for_prepare if target == "prepare" else ready_for_publish
    return {
        "ok": target_ok,
        "action": "onboard",
        "target": target,
        "readyForPrepare": ready_for_prepare,
        "readyForPublish": ready_for_publish,
        "configPath": str(resolved_config),
        "steps": steps,
        "nextActions": [
            {
                "id": step["id"],
                "title": step["title"],
                "userAction": step.get("userAction", ""),
                "agentAction": step.get("agentAction", ""),
            }
            for step in steps
            if step["status"] != "complete"
        ],
    }


def _step(
    step_id: str,
    title: str,
    status: str,
    summary: str,
    *,
    user_action: str = "",
    agent_action: str = "",
    blocking: bool = True,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "status": status,
        "summary": summary,
        "blocking": blocking,
        "userAction": user_action,
        "agentAction": agent_action,
        "details": dict(details or {}),
    }


def _all_complete(steps: Sequence[Mapping[str, Any]], ids: Sequence[str]) -> bool:
    statuses = {str(step["id"]): step["status"] for step in steps}
    return all(statuses.get(step_id) == "complete" for step_id in ids)


def _config_flavor(config: WorkerConfig | None) -> str:
    return config.feishu_cli_flavor if config else "lark"


def _first_env(env: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        value = env.get(key, "").strip()
        if value:
            return value
    return ""


def _check_lark_scopes(cli: str, scopes: Sequence[str], run: CommandRunner) -> dict[str, Any]:
    completed = run(
        [cli, "auth", "check", "--scope", " ".join(scopes)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "missing": list(scopes)}
    missing = payload.get("missing") or []
    return {"ok": completed.returncode == 0 and bool(payload.get("ok")), "missing": [str(item) for item in missing]}


def _print_chrome_profile(run: CommandRunner, chrome_profile: str) -> dict[str, Any]:
    command = [sys.executable, str(PINTEREST_CLI), "--print-chrome-profile"]
    if chrome_profile:
        command.extend(["--chrome-profile", chrome_profile])
    completed = run(command, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False}
    return payload if isinstance(payload, dict) else {"ok": False}


def _check_pinterest_login(run: CommandRunner, cdp_reachable: Callable[[], bool]) -> dict[str, Any]:
    if not cdp_reachable():
        return {"ok": False, "skipped": True, "reason": "Chrome CDP is not reachable"}
    completed = run(
        [
            sys.executable,
            str(PINTEREST_CLI),
            "--mode",
            "check-login",
            "--no-default-chrome-profile",
            "--timeout",
            "60",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "reason": "Pinterest CLI returned non-JSON output"}
    errors = payload.get("errors") if isinstance(payload, dict) else []
    return {
        "ok": completed.returncode == 0 and bool(isinstance(payload, dict) and payload.get("ok")),
        "reason": "; ".join(str(error) for error in (errors or [])[:2]),
    }


def _chrome_cdp_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2) as response:
            json.load(response)
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
