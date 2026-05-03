"""Hermes runtime boundary for scheduled Pinterest workflow runs."""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class RuntimeErrorConfig(ValueError):
    """Raised when the runtime cannot safely mutate external state."""


RUN_ID_KEYS = ("HERMES_RUN_ID", "HERMES_AGENT_RUN_ID", "RUN_ID")
AGENT_ID_KEYS = ("HERMES_AGENT_ID", "AGENT_ID")
JOB_ID_KEYS = ("HERMES_JOB_ID", "HERMES_SCHEDULE_ID", "JOB_ID")
TEMP_DIR_KEYS = ("PINTEREST_AUTOPIN_TMPDIR", "HERMES_TMPDIR", "HERMES_TEMP_DIR", "TMPDIR")
PROFILE_KEYS = ("PINTEREST_AUTOPIN_CHROME_PROFILE", "CHROME_PROFILE")


@dataclass(frozen=True)
class RuntimeContext:
    run_id: str
    hermes_run_id: str
    hermes_agent_id: str
    hermes_job_id: str
    temp_dir: Path
    chrome_profile: str
    local_dev: bool = False


def first_env(env: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        value = env.get(key, "").strip()
        if value:
            return value
    return ""


def ensure_required_secrets(env: Mapping[str, str], required: Sequence[str]) -> list[str]:
    return [name for name in required if not env.get(name, "").strip()]


def build_runtime_context(
    *,
    env: Mapping[str, str] | None = None,
    local_dev: bool = False,
    required_secrets: Sequence[str] = (),
    temp_dir: str | None = None,
    chrome_profile: str | None = None,
) -> RuntimeContext:
    runtime_env = env or os.environ
    missing_secrets = ensure_required_secrets(runtime_env, required_secrets)
    if missing_secrets:
        raise RuntimeErrorConfig(
            "missing required runtime secrets: " + ", ".join(sorted(missing_secrets))
        )

    hermes_run_id = first_env(runtime_env, RUN_ID_KEYS)
    hermes_agent_id = first_env(runtime_env, AGENT_ID_KEYS)
    hermes_job_id = first_env(runtime_env, JOB_ID_KEYS)

    if local_dev:
        local_id = f"local:{uuid.uuid4()}"
        hermes_run_id = hermes_run_id or local_id
        hermes_agent_id = hermes_agent_id or "local:agent"
        hermes_job_id = hermes_job_id or "local:job"
    elif not (hermes_run_id and hermes_agent_id and hermes_job_id):
        raise RuntimeErrorConfig(
            "Hermes run identity is required; pass --local-dev for explicit local runs"
        )

    root = temp_dir or first_env(runtime_env, TEMP_DIR_KEYS) or tempfile.gettempdir()
    run_temp_dir = Path(root).expanduser() / "pinterest-autopin" / hermes_run_id.replace(":", "-")
    run_temp_dir.mkdir(parents=True, exist_ok=True)

    profile = chrome_profile if chrome_profile is not None else first_env(runtime_env, PROFILE_KEYS)

    return RuntimeContext(
        run_id=hermes_run_id,
        hermes_run_id=hermes_run_id,
        hermes_agent_id=hermes_agent_id,
        hermes_job_id=hermes_job_id,
        temp_dir=run_temp_dir,
        chrome_profile=profile,
        local_dev=local_dev,
    )
