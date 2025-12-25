#!/usr/bin/env python3
"""Hyperliquid 仓位同步脚本.

目标：将 Follower 当前仓位调整到 Leader 仓位 * COPY_RATIO（默认 0.2）。

示例：
  python scripts/sync_positions.py --dry-run
  python scripts/sync_positions.py --execute
  python scripts/sync_positions.py --execute --force
  python scripts/sync_positions.py --config config/config.yaml --dry-run
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import eth_account
from dotenv import load_dotenv
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants


MIN_NOTIONAL_USD_DEFAULT = 10.0


@dataclass(frozen=True)
class Adjustment:
    coin: str
    is_buy: bool
    size: float
    price: float
    notional: float
    follower_before: float
    expected: float
    diff: float
    sz_decimals: int


def _round_down(size: float, decimals: int) -> float:
    try:
        decimals = int(decimals)
    except Exception:
        decimals = 3
    decimals = max(0, min(8, decimals))
    if size <= 0:
        return 0.0
    factor = 10 ** decimals
    return math.floor(float(size) * factor) / factor


def _load_repo_dotenv() -> None:
    try:
        repo_root = Path(__file__).resolve().parent.parent
        load_dotenv(dotenv_path=repo_root / ".env", override=False)
    except Exception:
        load_dotenv()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _get_positions_from_user_state(user_state: Dict[str, Any]) -> Dict[str, float]:
    positions: Dict[str, float] = {}
    asset_positions = user_state.get("assetPositions") if isinstance(user_state, dict) else None
    if not isinstance(asset_positions, list):
        return positions
    for entry in asset_positions:
        if not isinstance(entry, dict):
            continue
        position_data = entry.get("position") if isinstance(entry.get("position"), dict) else {}
        coin = position_data.get("coin") or entry.get("coin")
        if not coin:
            continue
        size = _safe_float(position_data.get("szi", 0), 0.0)
        if size == 0:
            continue
        positions[str(coin)] = float(size)
    return positions


def _get_sz_decimals_map(meta: Dict[str, Any]) -> Dict[str, int]:
    universe = meta.get("universe", []) if isinstance(meta, dict) else []
    mapping: Dict[str, int] = {}
    if not isinstance(universe, list):
        return mapping
    for a in universe:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        if not name:
            continue
        try:
            # IMPORTANT: szDecimals=0 is valid; don't use `or`.
            raw = a.get("szDecimals", 3)
            mapping[str(name)] = int(raw) if raw is not None else 3
        except Exception:
            mapping[str(name)] = 3
    return mapping


def _get_mid_prices(info: Info) -> Dict[str, float]:
    mids_raw = info.all_mids()
    mids: Dict[str, float] = {}
    if isinstance(mids_raw, dict):
        for k, v in mids_raw.items():
            try:
                mids[str(k)] = float(v)
            except Exception:
                continue
    return mids


def _chunk_order_sizes(
    total_size: float,
    *,
    price: float,
    sz_decimals: int,
    min_trade_size: float,
    max_notional_per_trade_usd: float,
    min_notional_usd: float,
) -> List[Tuple[float, float]]:
    """Return list of (size, notional) chunks."""
    remaining = float(abs(total_size))
    if remaining <= 0 or price <= 0:
        return []

    chunks: List[Tuple[float, float]] = []
    while remaining > 0:
        raw_size = remaining
        if max_notional_per_trade_usd and max_notional_per_trade_usd > 0:
            raw_size = min(raw_size, float(max_notional_per_trade_usd) / float(price))

        chunk = _round_down(raw_size, sz_decimals)
        if chunk <= 0:
            break

        if chunk < float(min_trade_size):
            break

        notional = float(chunk) * float(price)
        if notional < float(min_notional_usd):
            break

        chunks.append((float(chunk), float(notional)))
        remaining = max(0.0, remaining - float(chunk))

        # Safety: avoid an infinite loop due to rounding.
        if remaining > 0 and remaining < (10 ** (-max(0, min(8, int(sz_decimals))))):
            break

    return chunks


def compute_adjustments(
    *,
    leader_positions: Dict[str, float],
    follower_positions: Dict[str, float],
    mids: Dict[str, float],
    sz_decimals_by_coin: Dict[str, int],
    copy_ratio: float,
    min_trade_size: float,
    max_notional_per_trade_usd: float,
    min_notional_usd: float,
) -> List[Adjustment]:
    coins = sorted(set(leader_positions.keys()) | set(follower_positions.keys()))
    adjustments: List[Adjustment] = []

    for coin in coins:
        leader_size = float(leader_positions.get(coin, 0.0))
        follower_size = float(follower_positions.get(coin, 0.0))
        expected = leader_size * float(copy_ratio)
        diff = expected - follower_size

        if diff == 0:
            continue

        price = float(mids.get(coin, 0.0))
        if price <= 0:
            continue

        sz_decimals = int(sz_decimals_by_coin.get(coin, 3))
        chunks = _chunk_order_sizes(
            diff,
            price=price,
            sz_decimals=sz_decimals,
            min_trade_size=min_trade_size,
            max_notional_per_trade_usd=max_notional_per_trade_usd,
            min_notional_usd=min_notional_usd,
        )
        if not chunks:
            continue

        is_buy = diff > 0
        for chunk_size, notional in chunks:
            adjustments.append(
                Adjustment(
                    coin=coin,
                    is_buy=is_buy,
                    size=float(chunk_size),
                    price=float(price),
                    notional=float(notional),
                    follower_before=float(follower_size),
                    expected=float(expected),
                    diff=float(diff),
                    sz_decimals=int(sz_decimals),
                )
            )

    # Largest fixes first.
    return sorted(adjustments, key=lambda a: abs(a.diff) * a.price, reverse=True)


def _format_side(is_buy: bool) -> str:
    return "BUY " if is_buy else "SELL"


def _print_plan(adjustments: List[Adjustment]) -> None:
    if not adjustments:
        print("✅ No adjustments needed (within thresholds / constraints).")
        return

    total_notional = sum(a.notional for a in adjustments)
    print(f"Planned orders: {len(adjustments)} | Total notional: ${total_notional:,.2f}")
    print("coin      side   size          px        notional      follower_before    expected         diff")
    print("-" * 98)
    for a in adjustments:
        print(
            f"{a.coin:<8}  {_format_side(a.is_buy):<5}  {a.size:>10.6f}  "
            f"{a.price:>10.4f}  {a.notional:>12.2f}  {a.follower_before:>14.6f}  "
            f"{a.expected:>12.6f}  {a.diff:>12.6f}"
        )


def _confirm_or_exit(*, force: bool) -> None:
    if force:
        return
    ans = input("Execute these orders? Type 'yes' to continue: ").strip().lower()
    if ans != "yes":
        print("Aborted.")
        sys.exit(1)


def main(argv: Optional[Iterable[str]] = None) -> int:
    _load_repo_dotenv()

    parser = argparse.ArgumentParser(description="Hyperliquid follower 仓位同步脚本")
    parser.add_argument("--config", "-c", type=str, default=None, help="可选：YAML 配置文件路径")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只输出计划（默认）")
    mode.add_argument("--execute", action="store_true", help="执行调整下单")
    parser.add_argument("--force", action="store_true", help="执行时跳过二次确认")
    parser.add_argument("--copy-ratio", type=float, default=None, help="覆盖 COPY_RATIO（例如 0.2）")
    parser.add_argument("--min-notional", type=float, default=MIN_NOTIONAL_USD_DEFAULT, help="最小名义金额(USD)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    execute = bool(args.execute)
    dry_run = (not execute) or bool(args.dry_run)

    target_address = os.getenv("TARGET_ADDRESS", "").strip()
    account_address = os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", "").strip()
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "").strip()
    if not target_address or not account_address or not private_key:
        print("❌ Missing env: TARGET_ADDRESS, HYPERLIQUID_ACCOUNT_ADDRESS, HYPERLIQUID_PRIVATE_KEY")
        return 2

    use_testnet = os.getenv("HYPERLIQUID_ENV", "mainnet").strip().lower() == "testnet"
    base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL

    copy_ratio = args.copy_ratio if args.copy_ratio is not None else _safe_float(os.getenv("COPY_RATIO", "0.2"), 0.2)
    min_trade_size = _safe_float(os.getenv("MIN_TRADE_SIZE", "0.01"), 0.01)
    max_notional_per_trade_usd = _safe_float(os.getenv("MAX_NOTIONAL_PER_TRADE_USD", "0"), 0.0)
    min_notional_usd = float(args.min_notional)

    info = Info(base_url=base_url, skip_ws=True)
    wallet = eth_account.Account.from_key(private_key)
    exchange = Exchange(wallet=wallet, base_url=base_url, account_address=account_address)

    leader_state = info.user_state(target_address)
    follower_state = info.user_state(account_address)
    leader_positions = _get_positions_from_user_state(leader_state)
    follower_positions = _get_positions_from_user_state(follower_state)

    meta = info.meta()
    sz_decimals_by_coin = _get_sz_decimals_map(meta)
    mids = _get_mid_prices(info)

    adjustments = compute_adjustments(
        leader_positions=leader_positions,
        follower_positions=follower_positions,
        mids=mids,
        sz_decimals_by_coin=sz_decimals_by_coin,
        copy_ratio=copy_ratio,
        min_trade_size=min_trade_size,
        max_notional_per_trade_usd=max_notional_per_trade_usd,
        min_notional_usd=min_notional_usd,
    )

    print(f"Leader:   {target_address}")
    print(f"Follower: {account_address}")
    print(f"copy_ratio={copy_ratio} | min_trade_size={min_trade_size} | min_notional=${min_notional_usd} | max_notional_per_trade_usd={max_notional_per_trade_usd}")
    _print_plan(adjustments)

    if dry_run:
        return 0

    if not adjustments:
        return 0

    _confirm_or_exit(force=bool(args.force))
    ok = 0
    failed = 0
    for a in adjustments:
        try:
            result = exchange.market_open(a.coin, a.is_buy, a.size)
            print(f"✅ {a.coin} {_format_side(a.is_buy).strip()} {a.size} -> {result}")
            ok += 1
        except Exception as e:
            print(f"❌ {a.coin} {_format_side(a.is_buy).strip()} {a.size} failed: {e}")
            failed += 1

    print(f"Done. ok={ok} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

