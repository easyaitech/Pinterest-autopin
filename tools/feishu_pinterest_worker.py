#!/usr/bin/env python3
"""Hermes-native Feishu Pinterest worker CLI."""

from __future__ import annotations

import argparse
import json
import sys

from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pinterest_autopin.hermes_runtime import RuntimeErrorConfig
from pinterest_autopin.onboarding import DEFAULT_CONFIG, run_onboarding
from pinterest_autopin.worker import FeishuPinterestWorker, WorkerResult
from pinterest_autopin.worker_config import LOCK_MODE_HERMES_SINGLETON, ConfigError, load_worker_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Feishu-backed Pinterest workflow.")
    parser.add_argument("command", choices=("onboard", "doctor", "prepare", "publish"))
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to worker config JSON. Defaults to .gstack/feishu-worker-config.json.",
    )
    parser.add_argument("--limit", type=int, help="Maximum records to process.")
    parser.add_argument("--local-dev", action="store_true", help="Use explicit local:<uuid> run identity.")
    parser.add_argument("--chrome-profile", default="", help="Override Pinterest Chrome profile path.")
    parser.add_argument(
        "--skip-skill-update-check",
        action="store_true",
        help="Do not check the public skill version during onboarding.",
    )
    parser.add_argument(
        "--skip-pinterest-login-check",
        action="store_true",
        help="Do not run the live Pinterest check-login step during onboarding.",
    )
    parser.add_argument(
        "--publish-singleton-confirmed",
        action="store_true",
        help="Assert Hermes publish runs are configured with max concurrency 1.",
    )
    parser.add_argument(
        "--prepare-singleton-confirmed",
        action="store_true",
        help="Assert Hermes prepare runs are configured with max concurrency 1.",
    )
    parser.add_argument(
        "--target",
        choices=("prepare", "publish"),
        default="publish",
        help="Onboarding gate target. prepare ignores publish-only blockers.",
    )
    return parser.parse_args()


def print_json(payload: dict, exit_code: int) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return exit_code


def result_payload(result: WorkerResult) -> dict:
    return {
        "ok": result.ok,
        "action": result.action,
        "processed": result.processed,
        "skipped": result.skipped,
        "errors": list(result.errors),
    }


def main() -> int:
    args = parse_args()
    if args.command == "onboard":
        payload = run_onboarding(
            config_path=Path(args.config),
            local_dev=args.local_dev,
            chrome_profile=args.chrome_profile,
            check_updates=not args.skip_skill_update_check,
            check_pinterest_login=not args.skip_pinterest_login_check,
            prepare_singleton_confirmed=args.prepare_singleton_confirmed,
            publish_singleton_confirmed=args.publish_singleton_confirmed,
            target=args.target,
        )
        return print_json(payload, 0 if payload["ok"] else 1)

    try:
        config = load_worker_config(Path(args.config))
        config = apply_lock_overrides(
            config,
            prepare_singleton_confirmed=args.prepare_singleton_confirmed,
            publish_singleton_confirmed=args.publish_singleton_confirmed,
        )
        worker = FeishuPinterestWorker.from_config(
            config,
            local_dev=args.local_dev,
            chrome_profile=args.chrome_profile,
        )
        if args.command == "doctor":
            result = worker.doctor()
        elif args.command == "prepare":
            result = worker.prepare(limit=args.limit)
        else:
            result = worker.publish(limit=args.limit)
    except (ConfigError, RuntimeErrorConfig, Exception) as exc:  # noqa: BLE001
        return print_json({"ok": False, "action": args.command, "errors": [str(exc)]}, 1)

    return print_json(result_payload(result), 0 if result.ok else 1)


def apply_lock_overrides(
    config,
    *,
    prepare_singleton_confirmed: bool,
    publish_singleton_confirmed: bool,
):
    updates = {}
    if prepare_singleton_confirmed:
        updates["prepare_lock_mode"] = LOCK_MODE_HERMES_SINGLETON
    if publish_singleton_confirmed:
        updates["publish_lock_mode"] = LOCK_MODE_HERMES_SINGLETON
    return replace(config, **updates) if updates else config


if __name__ == "__main__":
    raise SystemExit(main())
