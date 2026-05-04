"""Skill version update checks for Hermes onboarding."""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request

from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_SKILL = REPO_ROOT / ".agents" / "skills" / "pinterest-autopin" / "SKILL.md"
DEFAULT_UPDATE_URL = (
    "https://raw.githubusercontent.com/easyaitech/Pinterest-autopin/main/"
    ".agents/skills/pinterest-autopin/SKILL.md"
)
UPDATE_URL_ENV = "PINTEREST_AUTOPIN_SKILL_UPDATE_URL"


def check_skill_update(
    *,
    local_skill: str | Path = LOCAL_SKILL,
    update_url: str | None = None,
    timeout: int = 4,
) -> dict[str, Any]:
    local_path = Path(local_skill)
    local_text = _read_text(local_path)
    local_meta = _front_matter(local_text)
    local_version = _version(local_meta)
    resolved_url = update_url or os.environ.get(UPDATE_URL_ENV, "").strip() or DEFAULT_UPDATE_URL

    try:
        remote_text = _fetch_text(resolved_url, timeout=timeout)
        remote_meta = _front_matter(remote_text)
        latest_version = _version(remote_meta)
    except Exception as exc:  # noqa: BLE001
        return {
            "checked": False,
            "ok": True,
            "updateAvailable": False,
            "localVersion": local_version,
            "latestVersion": "",
            "source": resolved_url,
            "reason": f"update check skipped: {exc}",
        }

    update_available = _compare_versions(latest_version, local_version) > 0
    return {
        "checked": True,
        "ok": True,
        "updateAvailable": update_available,
        "localVersion": local_version,
        "latestVersion": latest_version,
        "source": resolved_url,
        "upgradeCommand": _upgrade_command(),
        "reason": (
            f"Pinterest AutoPin skill {local_version} can be upgraded to {latest_version}."
            if update_available
            else f"Pinterest AutoPin skill is current at {local_version}."
        ),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _fetch_text(url: str, *, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "PinterestAutoPinSkillUpdate/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _front_matter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _version(meta: Mapping[str, str]) -> str:
    return str(meta.get("version") or "0.0.0").strip() or "0.0.0"


def _compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    return (left_parts > right_parts) - (left_parts < right_parts)


def _version_parts(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("v")
    parts = cleaned.split(".", 2)
    parsed: list[int] = []
    for part in parts:
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            elif digits:
                break
        parsed.append(int(digits or "0"))
    while len(parsed) < 3:
        parsed.append(0)
    return tuple(parsed[:3])  # type: ignore[return-value]


def _upgrade_command() -> str:
    if _is_git_repo(REPO_ROOT):
        return f"git -C {REPO_ROOT} pull --ff-only && npm --prefix {REPO_ROOT} install"
    return "Reinstall or update the pinterest-autopin skill from https://github.com/easyaitech/Pinterest-autopin"


def _is_git_repo(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"
