"""Wrapper around the existing Pinterest publishing CLI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISH_CLI = REPO_ROOT / "tools" / "pinterest_publish_pin.py"


class PublisherError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublisherResult:
    ok: bool
    mode: str
    pin_url: str = ""
    errors: tuple[str, ...] = ()
    raw: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PinterestPublisher:
    cli_path: Path = PUBLISH_CLI
    timeout: int = 600

    def check_login(self, *, chrome_profile: str = "") -> PublisherResult:
        command = [str(self.cli_path), "--mode", "check-login", "--timeout", str(self.timeout)]
        if chrome_profile:
            command.extend(["--chrome-profile", chrome_profile])
        return self._run(command, "check-login")

    def publish(self, request: Mapping[str, Any], *, input_path: Path, chrome_profile: str = "") -> PublisherResult:
        input_path.write_text(json.dumps(dict(request), ensure_ascii=True, indent=2), encoding="utf-8")
        command = [
            str(self.cli_path),
            "--mode",
            "final",
            "--input",
            str(input_path),
            "--timeout",
            str(self.timeout),
        ]
        if chrome_profile:
            command.extend(["--chrome-profile", chrome_profile])
        return self._run(command, "final")

    def _run(self, command: list[str], mode: str) -> PublisherResult:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=self.timeout)
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise PublisherError(f"Pinterest CLI returned non-JSON output: {exc}") from exc
        errors = tuple(str(error) for error in payload.get("errors", []) if error)
        ok = completed.returncode == 0 and bool(payload.get("ok"))
        return PublisherResult(
            ok=ok,
            mode=mode,
            pin_url=str(payload.get("pinUrl", "")),
            errors=errors,
            raw=payload,
        )
