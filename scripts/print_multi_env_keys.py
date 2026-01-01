#!/usr/bin/env python3
"""Print per-instance private key env vars for a multi-trader config.

Usage:
  .venv/bin/python scripts/print_multi_env_keys.py --config config/my_multi.yaml
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


def instance_env_suffix(name: str) -> str:
    raw = str(name or "").strip().upper()
    raw = re.sub(r"[^A-Z0-9]+", "_", raw).strip("_")
    return raw or "INSTANCE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/my_multi.yaml")
    args = parser.parse_args()

    path = Path(args.config)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    instances = cfg.get("trading_instances", []) or []

    print(f"Config: {path}")
    if not instances:
        print("No instances found.")
        return 0

    for inst in instances:
        name = str(inst.get("name") or "").strip()
        enabled = bool(inst.get("enabled", False))
        acct = str(((inst.get("hyperliquid") or {}).get("account_address") or "")).strip()
        target = str(inst.get("target_address") or "").strip()
        env_key = f"HYPERLIQUID_PRIVATE_KEY_{instance_env_suffix(name)}"
        state = "ENABLED" if enabled else "DISABLED"
        print(f"- {name} [{state}]")
        print(f"  - target_address: {target}")
        print(f"  - account_address: {acct}")
        print(f"  - private_key_env: {env_key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

