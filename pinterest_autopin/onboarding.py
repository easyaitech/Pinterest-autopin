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

from .skill_update import check_skill_update
from .worker import FeishuPinterestWorker
from .worker_config import (
    LOCK_MODE_FEISHU_ATOMIC,
    LOCK_MODE_HERMES_SINGLETON,
    ConfigError,
    WorkerConfig,
    load_worker_config,
    validate_worker_config,
)


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
UpdateChecker = Callable[[], dict[str, Any]]


def run_onboarding(
    *,
    config_path: str | Path | None = None,
    local_dev: bool = False,
    chrome_profile: str = "",
    check_updates: bool = True,
    check_pinterest_login: bool = True,
    prepare_singleton_confirmed: bool = False,
    publish_singleton_confirmed: bool = False,
    target: str = "publish",
    env: Mapping[str, str] | None = None,
    command_runner: CommandRunner | None = None,
    which: Which | None = None,
    cdp_reachable: Callable[[], bool] | None = None,
    update_checker: UpdateChecker | None = None,
) -> dict[str, Any]:
    runtime_env = dict(env or os.environ)
    run = command_runner or subprocess.run
    which_bin = which or shutil.which

    steps: list[dict[str, Any]] = []
    resolved_config = Path(config_path) if config_path else DEFAULT_CONFIG
    config: WorkerConfig | None = None

    skill_update = (
        (update_checker or check_skill_update)()
        if check_updates
        else {"checked": False, "updateAvailable": False, "reason": "Skipped by --skip-skill-update-check"}
    )
    update_available = bool(skill_update.get("updateAvailable"))
    steps.append(
        _step(
            "skill_update",
            "Check Pinterest AutoPin skill version",
            "action_required" if update_available else "complete",
            str(skill_update.get("reason") or "Skill update check completed."),
            user_action=(
                "A newer Pinterest AutoPin skill is available. Approve the upgrade before continuing."
                if update_available
                else ""
            ),
            agent_action=(
                "Ask the user for upgrade approval, then run: "
                + str(skill_update.get("upgradeCommand", ""))
                if update_available
                else ""
            ),
            blocking=False,
            details=skill_update,
        )
    )

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
    profile_exists = bool(profile_path) and Path(profile_path).exists()
    profile_ok = bool(profile.get("ok")) and bool(profile_path)
    steps.append(
        _step(
            "pinterest_profile",
            "Initialize dedicated Pinterest Chrome profile",
            "complete" if profile_ok and profile_exists else "action_required",
            (
                "Dedicated Pinterest Chrome profile exists."
                if profile_ok and profile_exists
                else "Initialize the dedicated Chrome profile before login."
            ),
            user_action="Let the agent initialize the profile, then sign in to Pinterest in that Chrome window.",
            agent_action="python3 tools/pinterest_publish_pin.py --init-chrome-profile",
            blocking=True,
            details={"profileSource": profile.get("chromeProfileSource", ""), "profileReady": profile_exists},
        )
    )

    pinterest_login = (
        _check_pinterest_login(run, profile_path if profile_exists else "")
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
            agent_action=_pinterest_login_agent_action(profile_path),
            blocking=True,
            details={
                "checked": not pinterest_login.get("skipped", False),
                "chromeProfile": profile_path,
                "reason": pinterest_login.get("reason", ""),
            },
        )
    )

    prepare_lock_ready = _lock_ready(config, "prepare", prepare_singleton_confirmed)
    steps.append(
        _step(
            "prepare_singleton",
            "Protect Feishu prepare claims",
            "complete" if prepare_lock_ready else "action_required",
            _lock_summary(config, "prepare", prepare_singleton_confirmed, prepare_lock_ready),
            user_action=(
                "Configure the Hermes prepare schedule with max concurrency 1, then pass "
                "--prepare-singleton-confirmed to onboard and prepare, or use an atomic compare-update wrapper."
            ),
            agent_action=(
                "Add prepare_lock_mode=hermes_singleton in the local config, or pass "
                "--prepare-singleton-confirmed on the Hermes prepare command."
            ),
            blocking=True,
            details={"lockMode": _effective_lock_mode(config, "prepare", prepare_singleton_confirmed)},
        )
    )

    publish_lock_ready = _lock_ready(config, "publish", publish_singleton_confirmed)
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
            user_action=(
                "Configure the Hermes publish schedule with max concurrency 1, then pass "
                "--publish-singleton-confirmed to onboard and publish."
            ),
            agent_action=(
                "Add publish_lock_mode=hermes_singleton in the local config, or pass "
                "--publish-singleton-confirmed on the Hermes publish command."
            ),
            blocking=True,
            details={"lockMode": _effective_lock_mode(config, "publish", publish_singleton_confirmed)},
        )
    )

    prepare_required = ["install_dependencies", "hermes_identity", "feishu_config", "feishu_cli", "feishu_doctor", "prepare_singleton"]
    if _config_flavor(config) == "lark":
        prepare_required.append("feishu_auth")
    ready_for_prepare = _all_complete(steps, prepare_required)
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


def _effective_lock_mode(config: WorkerConfig | None, action: str, singleton_confirmed: bool) -> str:
    if singleton_confirmed:
        return LOCK_MODE_HERMES_SINGLETON
    if not config:
        return LOCK_MODE_FEISHU_ATOMIC
    if action == "prepare":
        return config.prepare_lock_mode
    return config.publish_lock_mode


def _lock_ready(config: WorkerConfig | None, action: str, singleton_confirmed: bool) -> bool:
    mode = _effective_lock_mode(config, action, singleton_confirmed)
    if mode == LOCK_MODE_HERMES_SINGLETON:
        return True
    return bool(config) and _config_flavor(config) != "lark"


def _lock_summary(config: WorkerConfig | None, action: str, singleton_confirmed: bool, ready: bool) -> str:
    mode = _effective_lock_mode(config, action, singleton_confirmed)
    if ready and mode == LOCK_MODE_HERMES_SINGLETON:
        return f"Hermes {action} singleton is confirmed."
    if ready:
        return f"Feishu atomic compare-update protects {action} claims."
    return f"Official lark-cli cannot atomically claim {action} rows; configure Hermes singleton or an atomic wrapper."


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


def _pinterest_login_agent_action(profile_path: str) -> str:
    if profile_path:
        return f"python3 tools/pinterest_publish_pin.py --mode check-login --chrome-profile {profile_path}"
    return "python3 tools/pinterest_publish_pin.py --mode check-login"


def _check_pinterest_login(run: CommandRunner, chrome_profile: str) -> dict[str, Any]:
    if not chrome_profile:
        return {"ok": False, "skipped": True, "reason": "Dedicated Chrome profile is not ready"}
    completed = run(
        [
            sys.executable,
            str(PINTEREST_CLI),
            "--mode",
            "check-login",
            "--chrome-profile",
            chrome_profile,
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
