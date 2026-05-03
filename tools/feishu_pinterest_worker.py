#!/usr/bin/env python3
"""Hermes-native Feishu Pinterest worker CLI."""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pinterest_autopin.hermes_runtime import RuntimeErrorConfig
from pinterest_autopin.worker import FeishuPinterestWorker, WorkerResult
from pinterest_autopin.worker_config import ConfigError, load_worker_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Feishu-backed Pinterest workflow.")
    parser.add_argument("command", choices=("doctor", "prepare", "publish"))
    parser.add_argument("--config", required=True, help="Path to worker config JSON.")
    parser.add_argument("--limit", type=int, help="Maximum records to process.")
    parser.add_argument("--local-dev", action="store_true", help="Use explicit local:<uuid> run identity.")
    parser.add_argument("--chrome-profile", default="", help="Override Pinterest Chrome profile path.")
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
    try:
        config = load_worker_config(Path(args.config))
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


if __name__ == "__main__":
    raise SystemExit(main())
