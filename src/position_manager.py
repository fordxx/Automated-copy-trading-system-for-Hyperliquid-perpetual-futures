"""Position Manager for Hyperliquid Copy Trader.

负责管理跟单账户的仓位。
"""
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

import asyncio
import time
import math
import os

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from .trade_monitor import MonitoredTrade, TradeAction

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """仓位信息。"""

    coin: str
    size: float
    entry_price: float
    leverage: int
    pnl: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.size > 0

    @property
    def is_short(self) -> bool:
        return self.size < 0


@dataclass(frozen=True)
class SyncOrder:
    coin: str
    kind: str  # "open" | "close"
    size: float
    is_buy: Optional[bool]  # only meaningful for "open" (and for price gating decisions)
    price: float
    notional: float
    reason: str
    follower_before: float
    expected: float
    leader_entry_px: float
    reference_entry_px: float
    leader_leverage: int
    sz_decimals: int


class PositionManager:
    """仓位管理器。

    管理跟单账户的仓位，执行开仓、平仓等操作。
    """

    def __init__(self, exchange_client: Exchange, info_client: Info):
        self.exchange = exchange_client
        self.info = info_client
        self.positions: Dict[str, Position] = {}
        self._last_user_state: Optional[Dict[str, Any]] = None
        self._last_positions_update = 0.0
        # In practice user_state is the most rate-limit-prone call; keep a conservative floor.
        self._min_positions_update_interval = 2.0

        # 429 backoff handling
        self._consecutive_429_errors = 0
        self._backoff_until = 0.0
        self._max_backoff_s = 120.0

        # Debounced refresh to avoid double-refresh per trade burst
        self._refresh_task: Optional[asyncio.Task] = None

        # Cache for per-coin size decimals (szDecimals) to ensure orders meet
        # exchange precision constraints.
        self._sz_decimals_by_coin: Dict[str, int] = {}
        self._sz_decimals_fetched_at = 0.0
        self._sz_decimals_ttl_s = 3600.0
        # If we see an unknown coin (cache miss), refresh meta opportunistically.
        # This prevents using a wrong default precision for newly listed coins.
        self._sz_decimals_miss_refresh_at = 0.0
        self._sz_decimals_miss_refresh_cooldown_s = 30.0

        # Flip execution safety: optionally wait until the opposite position is actually closed
        # before opening the new side.
        self._flip_wait_for_close = os.getenv('FLIP_WAIT_FOR_CLOSE', 'true').lower() == 'true'
        self._flip_wait_timeout_s = float(os.getenv('FLIP_WAIT_TIMEOUT_S', '6'))
        self._flip_wait_poll_s = float(os.getenv('FLIP_WAIT_POLL_S', '0.75'))
        self._flip_open_on_timeout = os.getenv('FLIP_OPEN_ON_TIMEOUT', 'false').lower() == 'true'

        # Manual intervention cooldown:
        # If you manually flatten a position, ratio-sync should not "rebuild" it for a while.
        self._manual_position_cooldown_s = float(os.getenv('POSITION_SYNC_MANUAL_COOLDOWN_S', '0') or 0)
        self._manual_position_grace_s = float(os.getenv('POSITION_SYNC_MANUAL_GRACE_S', '30') or 30)
        self._manual_sync_cooldown_until_by_coin: Dict[str, float] = {}
        # Stronger behavior: after a manual flatten, never rebuild that coin via ratio-sync until
        # the leader fully closes (leader position goes to 0), at which point we "reset" the coin.
        self._manual_lock_until_leader_flat = os.getenv('POSITION_SYNC_MANUAL_LOCK_UNTIL_LEADER_FLAT', 'true').lower() == 'true'
        self._manual_locked_since_by_coin: Dict[str, float] = {}
        # Manual flatten detection robustness
        self._manual_zero_confirmations_required = int(os.getenv('POSITION_SYNC_MANUAL_CONFIRMATIONS', '2') or 2)
        self._manual_removed_confirmations_by_coin: Dict[str, int] = {}
        # Track last successful bot order per coin to avoid misclassifying bot closes as manual.
        self._last_bot_order_by_coin: Dict[str, Dict[str, Any]] = {}

        # Light caching to reduce REST load during sync planning.
        self._mids_cache: Dict[str, float] = {}
        self._mids_cache_at = 0.0
        self._mids_cache_ttl_s = float(os.getenv('POSITION_SYNC_MIDS_TTL_S', '2') or 2)
        self._fills_cache_at_by_leader: Dict[str, float] = {}
        self._fills_cache_by_leader: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._fills_cache_ttl_s = float(os.getenv('POSITION_SYNC_FILLS_TTL_S', '10') or 10)
        self._l2_cache_at_by_coin: Dict[str, float] = {}
        self._l2_cache_by_coin: Dict[str, Tuple[float, float, float]] = {}
        self._l2_cache_ttl_s = float(os.getenv('POSITION_SYNC_L2_TTL_S', '2') or 2)
        self._spread_unavailable_action = os.getenv('POSITION_SYNC_SPREAD_UNAVAILABLE_ACTION', 'skip').strip().lower()  # skip|ignore

        # Strict price gate optional fallback (time-based).
        self._strict_gate_max_wait_s = float(os.getenv('POSITION_SYNC_STRICT_MAX_WAIT_S', '0') or 0)
        self._strict_gate_first_skip_at: Dict[Tuple[str, str], float] = {}

        # Exchange minimum order notional guard (prevents 'Order must have minimum value of $10').
        # Used primarily for market_close: we buffer tiny close requests until they reach min notional.
        self._min_order_notional_usd = float(os.getenv('MIN_ORDER_NOTIONAL_USD', '10') or 10)
        self._pending_close_debt_by_coin: Dict[str, float] = {}

        # Per-coin execution locks: prevent concurrent order decisions/executions for the same coin
        # across different flows (real-time fills vs position sync/catch-up).
        self._coin_locks: Dict[str, asyncio.Lock] = {}

        logger.info("✅ PositionManager initialized")

    def _get_coin_lock(self, coin: str) -> asyncio.Lock:
        coin = str(coin or "")
        lock = self._coin_locks.get(coin)
        if lock is None:
            lock = asyncio.Lock()
            self._coin_locks[coin] = lock
        return lock

    async def initialize(self):
        """Initialize position manager (call after construction).

        Preheats the szDecimals cache to avoid 'Order has invalid size' errors
        on first trades.
        """
        logger.info("Preheating szDecimals cache...")
        try:
            await self._refresh_sz_decimals_cache()
            logger.info(f"✅ szDecimals cache preheated: {len(self._sz_decimals_by_coin)} coins loaded")
        except Exception as e:
            logger.warning(f"Failed to preheat szDecimals cache (will retry on demand): {e}")

    async def update_positions(self, force: bool = False, *, ignore_backoff: bool = False):
        """更新当前仓位信息。

        Args:
            force: If True, bypass local throttles/backoff and attempt refresh immediately.
                   Useful for emergency actions (e.g. stop-loss auto-flatten).
            ignore_backoff: If True, attempt refresh even if we are in a 429 backoff window.
        """
        try:
            now = time.monotonic()
            if (not ignore_backoff) and (now < self._backoff_until):
                return
            if not force:
                if (now - self._last_positions_update) < self._min_positions_update_interval:
                    return

            # 获取账户仓位（最容易触发 429）
            account_positions = await asyncio.to_thread(self.info.user_state, self.exchange.account_address)
            if isinstance(account_positions, dict):
                self._last_user_state = account_positions

            if not account_positions or "assetPositions" not in account_positions:
                logger.debug("No positions found")
                self.positions = {}
                self._last_positions_update = now
                return

            new_positions = {}
            for pos_data in account_positions["assetPositions"]:
                position_data = pos_data.get("position", {})

                # Hyperliquid user_state uses position.coin
                coin = position_data.get("coin") or pos_data.get("coin", "")
                if not coin:
                    continue

                size = float(position_data.get("szi", 0))
                if size == 0:
                    continue

                entry_price = float(position_data.get("entryPx", 0))
                leverage = int(position_data.get("leverage", {}).get("value", 1))
                pnl = float(position_data.get("unrealizedPnl", 0))

                position = Position(
                    coin=coin,
                    size=size,
                    entry_price=entry_price,
                    leverage=leverage,
                    pnl=pnl
                )

                new_positions[coin] = position

            # Detect manual flatten events (position existed -> gone) to set sync cooldown per coin.
            try:
                if self._manual_position_cooldown_s and self._manual_position_cooldown_s > 0:
                    now = time.monotonic()
                    removed = set(self.positions.keys()) - set(new_positions.keys())

                    # reset confirmations for coins that still exist
                    for coin in set(new_positions.keys()):
                        self._manual_removed_confirmations_by_coin.pop(str(coin), None)

                    for coin in removed:
                        prev = self.positions.get(coin)
                        if not prev or float(prev.size) == 0:
                            continue
                        last = self._last_bot_order_by_coin.get(coin) or {}
                        last_kind = str(last.get("kind", "") or "")
                        last_ts = float(last.get("ts", 0.0) or 0.0)
                        # If we recently submitted a close, don't treat it as manual.
                        recently_bot_closed = (last_kind == "close") and ((now - last_ts) <= float(self._manual_position_grace_s))
                        if recently_bot_closed:
                            continue

                        k = str(coin)
                        n = int(self._manual_removed_confirmations_by_coin.get(k, 0) or 0) + 1
                        self._manual_removed_confirmations_by_coin[k] = n
                        required = max(1, int(self._manual_zero_confirmations_required))
                        if n < required:
                            logger.warning(
                                "🟡 Manual flatten candidate: %s (prev=%s) confirmation %s/%s",
                                k,
                                float(prev.size),
                                n,
                                required,
                            )
                            continue

                        self._manual_sync_cooldown_until_by_coin[k] = now + float(self._manual_position_cooldown_s)
                        if self._manual_lock_until_leader_flat:
                            self._manual_locked_since_by_coin[k] = now
                        logger.warning(
                            "🛑 Manual position flatten detected: %s (prev=%s). Disabling ratio-sync for %.0fs",
                            k,
                            float(prev.size),
                            float(self._manual_position_cooldown_s),
                        )
            except Exception:
                # Never let this logic break normal position updates.
                pass

            self.positions = new_positions
            self._last_positions_update = now
            logger.debug(f"Updated positions: {len(self.positions)} positions")

            # success: reset 429 state
            self._consecutive_429_errors = 0

        except Exception as e:
            msg = str(e)
            if "429" in msg or "Too Many Requests" in msg:
                self._consecutive_429_errors += 1
                backoff = min((2 ** self._consecutive_429_errors) * 2.0, self._max_backoff_s)
                self._backoff_until = time.monotonic() + backoff
                logger.warning(f"⚠️ user_state rate-limited (429). Backing off {backoff:.1f}s (#{self._consecutive_429_errors})")
                return

            logger.error(f"Error updating positions: {e}")

    async def close_all_positions(self) -> Dict[str, Any]:
        """Attempt to close (flatten) all current positions.

        Returns a report with per-coin close attempts.
        """
        results: List[Dict[str, Any]] = []

        # Use the latest cached positions; callers may force-refresh beforehand.
        snapshot = list(self.positions.values())
        if not snapshot:
            return {"status": "noop", "closed": [], "errors": 0}

        errors = 0
        for pos in snapshot:
            try:
                coin = str(pos.coin)
                size_to_close = abs(float(pos.size))
                closed = await self._market_close_partial(coin, size_to_close)
                results.append({"coin": coin, "requested": size_to_close, "closed": float(closed or 0.0)})
            except Exception as e:
                errors += 1
                results.append({"coin": getattr(pos, 'coin', ''), "requested": abs(float(getattr(pos, 'size', 0.0) or 0.0)), "closed": 0.0, "error": str(e)})

        # Refresh lazily after close attempts.
        try:
            self.schedule_refresh(delay_s=1.0)
        except Exception:
            pass

        return {"status": "submitted", "closed": results, "errors": int(errors)}

    def get_account_value_usd(self, address: Optional[str] = None) -> Optional[float]:
        """Return the account value (equity) in USD.

        Args:
            address: If provided, fetch the account value for this address.
                    If None, use the cached user_state for the follower account.

        This comes from the cached user_state payload. We avoid extra REST calls here.
        """
        if address is None:
            # Use cached follower account state
            state = self._last_user_state
        else:
            # Fetch leader account state
            try:
                state = asyncio.run(asyncio.to_thread(self.info.user_state, address))
            except Exception as e:
                logger.warning(f"Failed to fetch account value for {address}: {e}")
                return None

        if not isinstance(state, dict):
            return None

        # Common shapes seen in Hyperliquid user_state payloads.
        candidates = [
            ("marginSummary", "accountValue"),
            ("crossMarginSummary", "accountValue"),
            ("summary", "accountValue"),
        ]
        for a, b in candidates:
            try:
                val = state.get(a, {}).get(b)
                if val is None:
                    continue
                return float(val)
            except Exception:
                continue

        # Fallback: some payloads may use a flat key.
        for key in ("accountValue", "equity", "totalAccountValue"):
            try:
                val = state.get(key)
                if val is None:
                    continue
                return float(val)
            except Exception:
                continue

        return None

    def schedule_refresh(self, delay_s: float = 1.0):
        """Schedule a debounced positions refresh.

        Used after placing orders so bursts don't trigger immediate repeated user_state calls.
        """
        if self._refresh_task and not self._refresh_task.done():
            return

        async def _runner():
            await asyncio.sleep(max(0.0, float(delay_s)))
            await self.update_positions()

        self._refresh_task = asyncio.create_task(_runner())

    def get_position(self, coin: str) -> Optional[Position]:
        """获取指定币种的仓位。"""
        return self.positions.get(coin)

    async def execute_copy_trade(
        self,
        trade: MonitoredTrade,
        copy_ratio: float,
        max_size: float,
        max_leverage: int = 5,
        max_notional_per_trade_usd: float = 0.0,
        min_trade_size: float = 0.01,
        copy_mode: str = "position",
        leader_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行跟单交易（极速开/平）。

        Args:
            copy_mode: "position" (根据仓位大小比例) 或 "wallet" (根据钱包余额比例)
            leader_address: Leader地址，wallet模式下需要此参数获取其钱包余额

        策略：
        - 优先使用 fill 的 side(B=买/A=卖) 来决定方向。
        - 如果方向与当前持仓相反，则优先 reduce/close（极速平仓）。
        - SDK 调用全部放到线程，避免阻塞 asyncio 事件循环。
        """
        coin = str(getattr(trade, "coin", "") or "")
        if not coin:
            return {"status": "skipped", "reason": "missing_coin", "coin": "", "action": str(getattr(trade, "action", ""))}

        lock = self._get_coin_lock(coin)
        await lock.acquire()
        try:
            # 根据copy_mode计算实际的copy_ratio
            actual_copy_ratio = copy_ratio
            if copy_mode == "wallet" and leader_address:
                # 钱包模式：根据钱包余额比例计算
                try:
                    follower_balance = self.get_account_value_usd()
                    leader_balance = self.get_account_value_usd(leader_address)
                    
                    if follower_balance and leader_balance and leader_balance > 0:
                        actual_copy_ratio = follower_balance / leader_balance
                        logger.info(
                            f"💰 Wallet mode: Follower={follower_balance:.2f}U, "
                            f"Leader={leader_balance:.2f}U, Ratio={actual_copy_ratio:.4f}"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Wallet mode failed (follower={follower_balance}, leader={leader_balance}), "
                            f"fallback to position mode with ratio={copy_ratio}"
                        )
                except Exception as e:
                    logger.error(f"Failed to calculate wallet ratio: {e}, using position mode ratio={copy_ratio}")
            
            requested_size = float(getattr(trade, 'size', 0) or 0) * float(actual_copy_ratio)
            copy_size_before_caps = float(requested_size)
            copy_size = float(requested_size)

            # Optional notional cap (USD): cap size based on fill price.
            px = float(getattr(trade, 'price', 0) or 0)
            max_notional = float(max_notional_per_trade_usd or 0.0)
            max_size_contracts = float(max_size)
            cap_by_size = False
            cap_by_notional = False
            if max_size_contracts > 0:
                if copy_size > max_size_contracts:
                    cap_by_size = True
                copy_size = min(copy_size, max_size_contracts)
            if max_notional > 0 and px > 0:
                notional_cap_size = max_notional / px
                if copy_size > notional_cap_size:
                    cap_by_notional = True
                copy_size = min(copy_size, notional_cap_size)

            # Round size to allowed precision.
            decimals = await self._get_sz_decimals(coin)
            copy_size_rounded = self._round_down(copy_size, decimals)
            rounded_down = copy_size_rounded != copy_size
            copy_size = copy_size_rounded
            min_sz = float(min_trade_size or 0.0)
            if copy_size < min_sz:
                logger.info(f"Copy size {copy_size} too small, skipping")
                return {
                    "status": "skipped",
                    "reason": "too_small",
                    "coin": trade.coin,
                    "action": str(trade.action),
                    "requested_size": float(requested_size),
                    "order_size": 0.0,
                    "max_size": float(max_size),
                    "max_notional_per_trade_usd": float(max_notional),
                    "min_trade_size": float(min_sz),
                    "capped_by_size": bool(cap_by_size),
                    "capped_by_notional": bool(cap_by_notional),
                    "rounded_down": bool(rounded_down),
                    "sz_decimals": int(decimals),
                }

            position = self.get_position(coin)

            # Reduce-only semantics: if the leader is closing but we have no position,
            # do NOT open a reverse position.
            if trade.action == TradeAction.CLOSE_LONG:
                if not position or not position.is_long:
                    pos_size = float(position.size) if position else 0.0
                    logger.info(
                        "SKIP CLOSE (no follower position): coin=%s action=%s leader_size=%s copy_ratio=%s copy_size=%s follower_pos=%s",
                        coin,
                        trade.action,
                        float(getattr(trade, 'size', 0) or 0),
                        float(copy_ratio),
                        float(copy_size),
                        pos_size,
                    )
                    return {
                        "status": "skipped",
                        "reason": "no_follower_position",
                        "coin": coin,
                        "action": str(trade.action),
                        "requested_size": float(requested_size),
                        "order_size": 0.0,
                        "max_size": float(max_size),
                        "max_notional_per_trade_usd": float(max_notional),
                        "min_trade_size": float(min_sz),
                        "capped_by_size": bool(cap_by_size),
                        "capped_by_notional": bool(cap_by_notional),
                        "rounded_down": bool(rounded_down),
                        "sz_decimals": int(decimals),
                        "follower_pos": float(pos_size),
                    }
                logger.info(
                    "EXEC CLOSE: coin=%s action=%s leader_size=%s copy_ratio=%s copy_size=%s follower_pos=%s",
                    coin,
                    trade.action,
                    float(getattr(trade, 'size', 0) or 0),
                    float(copy_ratio),
                    float(copy_size),
                    float(position.size),
                )
                closed = await self._market_close_partial(coin, copy_size)
                self.schedule_refresh(delay_s=1.0)
                return {
                    "status": "submitted",
                    "reason": None,
                    "coin": coin,
                    "action": str(trade.action),
                    "requested_size": float(requested_size),
                    "order_size": float(closed or 0.0),
                    "max_size": float(max_size),
                    "max_notional_per_trade_usd": float(max_notional),
                    "min_trade_size": float(min_sz),
                    "capped_by_size": bool(cap_by_size),
                    "capped_by_notional": bool(cap_by_notional),
                    "rounded_down": bool(rounded_down),
                    "sz_decimals": int(decimals),
                    "follower_pos": float(position.size),
                }

            if trade.action == TradeAction.CLOSE_SHORT:
                if not position or not position.is_short:
                    pos_size = float(position.size) if position else 0.0
                    logger.info(
                        "SKIP CLOSE (no follower position): coin=%s action=%s leader_size=%s copy_ratio=%s copy_size=%s follower_pos=%s",
                        coin,
                        trade.action,
                        float(getattr(trade, 'size', 0) or 0),
                        float(copy_ratio),
                        float(copy_size),
                        pos_size,
                    )
                    return {
                        "status": "skipped",
                        "reason": "no_follower_position",
                        "coin": coin,
                        "action": str(trade.action),
                        "requested_size": float(requested_size),
                        "order_size": 0.0,
                        "max_size": float(max_size),
                        "max_notional_per_trade_usd": float(max_notional),
                        "min_trade_size": float(min_sz),
                        "capped_by_size": bool(cap_by_size),
                        "capped_by_notional": bool(cap_by_notional),
                        "rounded_down": bool(rounded_down),
                        "sz_decimals": int(decimals),
                        "follower_pos": float(pos_size),
                    }
                logger.info(
                    "EXEC CLOSE: coin=%s action=%s leader_size=%s copy_ratio=%s copy_size=%s follower_pos=%s",
                    coin,
                    trade.action,
                    float(getattr(trade, 'size', 0) or 0),
                    float(copy_ratio),
                    float(copy_size),
                    float(position.size),
                )
                closed = await self._market_close_partial(coin, copy_size)
                self.schedule_refresh(delay_s=1.0)
                return {
                    "status": "submitted",
                    "reason": None,
                    "coin": coin,
                    "action": str(trade.action),
                    "requested_size": float(requested_size),
                    "order_size": float(closed or 0.0),
                    "max_size": float(max_size),
                    "max_notional_per_trade_usd": float(max_notional),
                    "min_trade_size": float(min_sz),
                    "capped_by_size": bool(cap_by_size),
                    "capped_by_notional": bool(cap_by_notional),
                    "rounded_down": bool(rounded_down),
                    "sz_decimals": int(decimals),
                    "follower_pos": float(position.size),
                }

            side = getattr(trade, 'side', None)
            if side in ("B", "A"):
                is_buy = side == "B"
            else:
                is_buy = trade.action == TradeAction.OPEN_LONG

            leverage = int(getattr(trade, 'leverage', 1) or 1)
            leverage = max(1, min(leverage, int(max_leverage)))

            async def _wait_no_opposite_position(*, want_buy: bool, decimals_for_eps: int) -> bool:
                if not self._flip_wait_for_close:
                    return True
                timeout_s = max(0.0, float(self._flip_wait_timeout_s))
                if timeout_s <= 0:
                    return True
                poll_s = max(0.25, float(self._flip_wait_poll_s))
                eps = max(1e-12, 10 ** (-max(0, int(decimals_for_eps))))

                deadline = time.monotonic() + timeout_s
                while time.monotonic() < deadline:
                    # Force update and ignore backoff to ensure we get fresh position data
                    await self.update_positions(force=True, ignore_backoff=True)
                    pos_now = self.get_position(coin)
                    size_now = float(pos_now.size) if pos_now else 0.0

                    # want_buy=True means we're going to open long, so we must not still be short.
                    if want_buy:
                        if size_now >= -eps:
                            return True
                    else:
                        if size_now <= eps:
                            return True

                    await asyncio.sleep(poll_s)
                return False

            if is_buy and position and position.is_short:
                # Flip support: close short first, then open long for the remaining size.
                close_req = min(float(copy_size), abs(float(position.size)))
                closed = await self._market_close_partial(coin, close_req)
                remaining = max(0.0, float(copy_size) - float(closed or 0.0))
                opened = 0.0
                # Only attempt to open remainder if we intended to fully close the opposite position.
                full_close_intended = abs(float(position.size)) <= (float(close_req) + max(1e-12, 10 ** (-max(0, int(decimals)))))
                if remaining >= min_sz and full_close_intended:
                    ok = await _wait_no_opposite_position(want_buy=True, decimals_for_eps=int(decimals))
                    if (not ok) and (not self._flip_open_on_timeout):
                        self.schedule_refresh(delay_s=1.0)
                        return {
                            "status": "submitted",
                            "reason": "flip_wait_timeout",
                            "coin": coin,
                            "action": str(trade.action),
                            "requested_size": float(requested_size),
                            "order_size": float(copy_size),
                            "closed_size": float(closed or 0.0),
                            "opened_size": 0.0,
                            "max_size": float(max_size),
                            "max_notional_per_trade_usd": float(max_notional),
                            "min_trade_size": float(min_sz),
                            "capped_by_size": bool(cap_by_size),
                            "capped_by_notional": bool(cap_by_notional),
                            "rounded_down": bool(rounded_down),
                            "sz_decimals": int(decimals),
                            "follower_pos": float(position.size),
                        }

                    await self._set_leverage(coin, leverage)
                    await self._market_open(coin, True, remaining)
                    opened = float(remaining)
                self.schedule_refresh(delay_s=1.0)
                return {
                    "status": "submitted",
                    "reason": "flip" if opened > 0 else "close_only",
                    "coin": coin,
                    "action": str(trade.action),
                    "requested_size": float(requested_size),
                    # Keep backward compatibility: order_size reflects the intended total.
                    "order_size": float(copy_size),
                    "closed_size": float(closed or 0.0),
                    "opened_size": float(opened or 0.0),
                    "max_size": float(max_size),
                    "max_notional_per_trade_usd": float(max_notional),
                    "min_trade_size": float(min_sz),
                    "capped_by_size": bool(cap_by_size),
                    "capped_by_notional": bool(cap_by_notional),
                    "rounded_down": bool(rounded_down),
                    "sz_decimals": int(decimals),
                    "follower_pos": float(position.size),
                }
            elif (not is_buy) and position and position.is_long:
                # Flip support: close long first, then open short for the remaining size.
                close_req = min(float(copy_size), abs(float(position.size)))
                closed = await self._market_close_partial(coin, close_req)
                remaining = max(0.0, float(copy_size) - float(closed or 0.0))
                opened = 0.0
                full_close_intended = abs(float(position.size)) <= (float(close_req) + max(1e-12, 10 ** (-max(0, int(decimals)))))
                if remaining >= min_sz and full_close_intended:
                    ok = await _wait_no_opposite_position(want_buy=False, decimals_for_eps=int(decimals))
                    if (not ok) and (not self._flip_open_on_timeout):
                        self.schedule_refresh(delay_s=1.0)
                        return {
                            "status": "submitted",
                            "reason": "flip_wait_timeout",
                            "coin": coin,
                            "action": str(trade.action),
                            "requested_size": float(requested_size),
                            "order_size": float(copy_size),
                            "closed_size": float(closed or 0.0),
                            "opened_size": 0.0,
                            "max_size": float(max_size),
                            "max_notional_per_trade_usd": float(max_notional),
                            "min_trade_size": float(min_sz),
                            "capped_by_size": bool(cap_by_size),
                            "capped_by_notional": bool(cap_by_notional),
                            "rounded_down": bool(rounded_down),
                            "sz_decimals": int(decimals),
                            "follower_pos": float(position.size),
                        }

                    await self._set_leverage(coin, leverage)
                    await self._market_open(coin, False, remaining)
                    opened = float(remaining)
                self.schedule_refresh(delay_s=1.0)
                return {
                    "status": "submitted",
                    "reason": "flip" if opened > 0 else "close_only",
                    "coin": coin,
                    "action": str(trade.action),
                    "requested_size": float(requested_size),
                    "order_size": float(copy_size),
                    "closed_size": float(closed or 0.0),
                    "opened_size": float(opened or 0.0),
                    "max_size": float(max_size),
                    "max_notional_per_trade_usd": float(max_notional),
                    "min_trade_size": float(min_sz),
                    "capped_by_size": bool(cap_by_size),
                    "capped_by_notional": bool(cap_by_notional),
                    "rounded_down": bool(rounded_down),
                    "sz_decimals": int(decimals),
                    "follower_pos": float(position.size),
                }
            else:
                await self._set_leverage(coin, leverage)
                await self._market_open(coin, is_buy, copy_size)

                # Refresh positions lazily to avoid user_state bursts (and 429).
                self.schedule_refresh(delay_s=1.0)
                return {
                    "status": "submitted",
                    "reason": None,
                    "coin": coin,
                    "action": str(trade.action),
                    "requested_size": float(requested_size),
                    "order_size": float(copy_size),
                    "max_size": float(max_size),
                    "max_notional_per_trade_usd": float(max_notional),
                    "min_trade_size": float(min_sz),
                    "capped_by_size": bool(cap_by_size),
                    "capped_by_notional": bool(cap_by_notional),
                    "rounded_down": bool(rounded_down),
                    "sz_decimals": int(decimals),
                }

        except Exception as e:
            logger.error(f"Error executing copy trade: {e}")
            return {
                "status": "error",
                "reason": str(e),
                "coin": getattr(trade, 'coin', ''),
                "action": str(getattr(trade, 'action', '')),
                "requested_size": float(getattr(trade, 'size', 0) or 0) * float(copy_ratio),
                "order_size": 0.0,
                "max_size": float(max_size),
                "max_notional_per_trade_usd": float(max_notional_per_trade_usd or 0.0),
            }
        finally:
            try:
                lock.release()
            except Exception:
                pass

    async def _refresh_sz_decimals_cache(self) -> None:
        """Refresh szDecimals cache from meta API.

        Extracted as separate method to enable both preheating and on-demand refresh.
        """
        try:
            meta = await asyncio.to_thread(self.info.meta)
            universe = meta.get('universe', []) if isinstance(meta, dict) else []
            mapping: Dict[str, int] = {}
            for a in universe:
                name = a.get('name')
                if not name:
                    continue
                try:
                    # NOTE: Do NOT use "or 3" here - it breaks coins with szDecimals=0 (e.g., ANIME)
                    # because 0 is falsy in Python, so "0 or 3" evaluates to 3.
                    sz_dec_raw = a.get('szDecimals', 3)
                    sz_dec = int(sz_dec_raw) if sz_dec_raw is not None else 3
                    mapping[str(name)] = sz_dec
                except Exception:
                    mapping[str(name)] = 3
            if mapping:
                self._sz_decimals_by_coin = mapping
                self._sz_decimals_fetched_at = time.monotonic()
                logger.debug(f"szDecimals cache refreshed: {len(mapping)} coins")
            else:
                logger.warning("szDecimals refresh returned empty mapping")
        except Exception as e:
            # Keep old cache on failure
            logger.warning(f"Failed to refresh szDecimals cache: {e}")

    async def _get_sz_decimals(self, coin: str) -> int:
        """Get allowed size decimals for a coin (szDecimals).

        Uses cached meta universe to avoid frequent REST calls.
        Defaults to 3 if unavailable.
        """
        coin = str(coin or '')
        if not coin:
            logger.debug("_get_sz_decimals called with empty coin, returning default 3")
            return 3

        now = time.monotonic()

        # Refresh on TTL expiry.
        if (now - self._sz_decimals_fetched_at) > self._sz_decimals_ttl_s:
            logger.debug(f"szDecimals cache TTL expired, refreshing...")
            await self._refresh_sz_decimals_cache()

        # If coin is missing, refresh opportunistically (new listings) but throttle.
        if coin not in self._sz_decimals_by_coin:
            # Log cache inspection for debugging
            logger.info(f"🔍 szDecimals cache MISS for '{coin}' (type={type(coin).__name__}, len={len(coin)}, repr={repr(coin)})")
            logger.info(f"   Cache has {len(self._sz_decimals_by_coin)} entries. Sample keys: {list(self._sz_decimals_by_coin.keys())[:10]}")
            # Check for case-insensitive or whitespace variants
            similar_keys = [k for k in self._sz_decimals_by_coin.keys() if coin.strip().upper() == k.strip().upper()]
            if similar_keys:
                logger.warning(f"   Found similar keys (case/whitespace differ): {similar_keys}")

            if (now - self._sz_decimals_miss_refresh_at) > self._sz_decimals_miss_refresh_cooldown_s:
                logger.info(f"   Refreshing cache for potential new listing...")
                self._sz_decimals_miss_refresh_at = now
                await self._refresh_sz_decimals_cache()

        if coin in self._sz_decimals_by_coin:
            decimals = int(self._sz_decimals_by_coin[coin])
            logger.info(f"✅ szDecimals for '{coin}': {decimals}")
            return decimals

        logger.warning(f"❌ szDecimals not found for '{coin}', using default 3")
        return 3

    def _extract_order_error(self, result: Any) -> Optional[str]:
        """Extract an order error from common Hyperliquid SDK response shapes."""
        if not isinstance(result, dict):
            return None

        # Some responses may include a top-level error.
        for key in ("error", "err", "message"):
            try:
                v = result.get(key)
                if v:
                    return str(v)
            except Exception:
                pass

        try:
            resp = result.get("response")
            if isinstance(resp, dict):
                data = resp.get("data")
                if isinstance(data, dict):
                    statuses = data.get("statuses")
                    if isinstance(statuses, list):
                        errors = []
                        for s in statuses:
                            if isinstance(s, dict) and s.get("error"):
                                errors.append(str(s.get("error")))
                        if errors:
                            return "; ".join(errors)
        except Exception:
            pass

        return None

    def _round_down(self, size: float, decimals: int) -> float:
        try:
            decimals = int(decimals)
        except Exception:
            decimals = 3
        decimals = max(0, min(8, decimals))
        if size <= 0:
            return 0.0
        factor = 10 ** decimals
        return math.floor(float(size) * factor) / factor

    async def _market_open(self, coin: str, is_buy: bool, size: float):
        try:
            logger.info(f"📤 _market_open called: coin='{coin}' (type={type(coin).__name__}, repr={repr(coin)}) is_buy={is_buy} size={size}")
            decimals = await self._get_sz_decimals(coin)
            size_before_round = float(size)
            size = self._round_down(size_before_round, decimals)
            if size <= 0:
                logger.info(f"Market open skipped (rounded size=0): {coin}")
                return
            logger.info(f"Market open: {coin} {'BUY' if is_buy else 'SELL'} size={size} (before_round={size_before_round:.6f}, szDecimals={decimals})")
            result = await asyncio.to_thread(self.exchange.market_open, coin, is_buy, size)
            logger.info(f"Market open result: {coin} {size} -> {result}")
            err = self._extract_order_error(result)
            if err:
                raise RuntimeError(f"market_open rejected: {err}")
            try:
                self._last_bot_order_by_coin[str(coin)] = {"kind": "open", "ts": time.monotonic()}
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error market_open {coin}: {e}")
            raise

    async def _market_close_partial(self, coin: str, size: float) -> float:
        try:
            position = self.get_position(coin)
            if not position or position.size == 0:
                logger.warning(f"No position to close for {coin}")
                return 0.0

            decimals = await self._get_sz_decimals(coin)
            coin_key = str(coin)

            requested = max(0.0, float(size))
            if requested <= 0:
                return 0.0

            debt = float(self._pending_close_debt_by_coin.get(coin_key, 0.0) or 0.0)
            desired = min(requested + max(0.0, debt), abs(float(position.size)))

            close_size = desired
            close_size = self._round_down(close_size, decimals)
            if close_size <= 0:
                logger.info(f"Market close skipped (rounded size=0): {coin}")
                return 0.0

            # Pre-check minimum notional: buffer tiny close requests instead of submitting/rejecting.
            min_notional = float(self._min_order_notional_usd or 0.0)
            if min_notional > 0:
                mids = await self._get_mid_prices()
                mid = float(mids.get(coin_key, 0.0) or 0.0)
                notional = float(close_size) * float(mid) if mid > 0 else 0.0
                if notional < min_notional:
                    # Keep desired (pre-round) so future requests can accumulate.
                    self._pending_close_debt_by_coin[coin_key] = float(desired)
                    logger.warning(
                        "🧩 Close buffered (min notional): %s size=%.6f mid=%.6g notional=$%.2f < $%.2f (debt=%.6f)",
                        coin_key,
                        float(close_size),
                        float(mid),
                        float(notional),
                        float(min_notional),
                        float(desired),
                    )
                    return 0.0

            result = await asyncio.to_thread(self.exchange.market_close, coin, close_size)
            logger.info(f"Market close: {coin} {close_size}, result: {result}")
            err = self._extract_order_error(result)
            if err:
                # If still rejected due to min notional (price moved), keep buffering instead of raising.
                if "minimum value" in str(err).lower():
                    self._pending_close_debt_by_coin[coin_key] = float(desired)
                    logger.warning(f"🧩 Close buffered after reject (min notional): {coin_key} desired={desired} err={err}")
                    return 0.0
                raise RuntimeError(f"market_close rejected: {err}")

            # Successful submission: clear or reduce debt based on what we actually sent.
            remaining = max(0.0, float(desired) - float(close_size))
            if remaining > 0:
                self._pending_close_debt_by_coin[coin_key] = float(remaining)
            else:
                self._pending_close_debt_by_coin.pop(coin_key, None)
            try:
                self._last_bot_order_by_coin[str(coin)] = {"kind": "close", "ts": time.monotonic()}
            except Exception:
                pass
            return float(close_size)
        except Exception as e:
            logger.error(f"Error market_close {coin}: {e}")
            raise

    def is_ratio_sync_blocked(self, coin: str) -> bool:
        """Return True if ratio-sync for this coin is temporarily blocked due to manual intervention."""
        try:
            until = float(self._manual_sync_cooldown_until_by_coin.get(str(coin), 0.0) or 0.0)
        except Exception:
            return False
        if until <= 0:
            return False
        return time.monotonic() < until

    async def _set_leverage(self, coin: str, leverage: int):
        """设置杠杆。"""
        try:
            # SDK signature: update_leverage(leverage, name, is_cross=True)
            await asyncio.to_thread(self.exchange.update_leverage, int(leverage), coin)
            logger.debug(f"Set leverage for {coin} to {leverage}")
        except Exception as e:
            logger.error(f"Error setting leverage: {e}")

    def get_total_pnl(self) -> float:
        """获取总未实现盈亏。"""
        return sum(pos.pnl for pos in self.positions.values())

    def get_positions_summary(self) -> Dict[str, Any]:
        """获取仓位汇总信息。"""
        return {
            "total_positions": len(self.positions),
            "total_pnl": self.get_total_pnl(),
            "positions": [
                {
                    "coin": pos.coin,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "leverage": pos.leverage,
                    "pnl": pos.pnl,
                    "direction": "long" if pos.is_long else "short"
                }
                for pos in self.positions.values()
            ]
        }

    async def get_mid_prices(self) -> Dict[str, float]:
        """Get current mid prices map {coin: mid} (cached)."""
        return await self._get_mid_prices()

    # -------------------------
    # Position sync (ratio fix)
    # -------------------------

    def _positions_from_user_state_with_entry(self, user_state: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """Extract {coin: {size, entry_px, leverage}} from a Hyperliquid user_state payload."""
        out: Dict[str, Dict[str, float]] = {}
        asset_positions = user_state.get("assetPositions") if isinstance(user_state, dict) else None
        if not isinstance(asset_positions, list):
            return out
        for entry in asset_positions:
            if not isinstance(entry, dict):
                continue
            position_data = entry.get("position") if isinstance(entry.get("position"), dict) else {}
            coin = position_data.get("coin") or entry.get("coin")
            if not coin:
                continue
            try:
                size = float(position_data.get("szi", 0) or 0)
            except Exception:
                size = 0.0
            if size == 0:
                continue
            try:
                entry_px = float(position_data.get("entryPx", 0) or 0)
            except Exception:
                entry_px = 0.0
            try:
                lev = int(position_data.get("leverage", {}).get("value", 1) or 1)
            except Exception:
                lev = 1
            out[str(coin)] = {"size": float(size), "entry_px": float(entry_px), "leverage": float(lev)}
        return out

    async def _get_mid_prices(self) -> Dict[str, float]:
        now = time.monotonic()
        if self._mids_cache and (now - float(self._mids_cache_at)) <= float(self._mids_cache_ttl_s):
            return dict(self._mids_cache)

        try:
            mids_raw = await asyncio.to_thread(self.info.all_mids)
        except Exception as e:
            logger.warning(f"Failed to fetch mids: {e}")
            return dict(self._mids_cache) if self._mids_cache else {}
        mids: Dict[str, float] = {}
        if isinstance(mids_raw, dict):
            for k, v in mids_raw.items():
                try:
                    mids[str(k)] = float(v)
                except Exception:
                    continue
        if mids:
            self._mids_cache = dict(mids)
            self._mids_cache_at = now
        return mids

    async def _get_best_bid_ask(self, coin: str) -> Optional[Tuple[float, float]]:
        """Return (best_bid, best_ask) from L2 snapshot if available."""
        coin = str(coin or "")
        if not coin:
            return None
        now = time.monotonic()
        cached = self._l2_cache_by_coin.get(coin)
        cached_at = float(self._l2_cache_at_by_coin.get(coin, 0.0) or 0.0)
        if cached and (now - cached_at) <= float(self._l2_cache_ttl_s):
            bid, ask, _sbps = cached
            if bid > 0 and ask > 0:
                return float(bid), float(ask)
        try:
            snap = await asyncio.to_thread(self.info.l2_snapshot, coin)
        except Exception as e:
            logger.debug(f"Failed to fetch l2_snapshot for {coin}: {e}")
            return None

        if not isinstance(snap, dict):
            return None
        levels = snap.get("levels")
        if not (isinstance(levels, list) and len(levels) >= 2):
            return None
        bids = levels[0]
        asks = levels[1]
        if not (isinstance(bids, list) and bids and isinstance(asks, list) and asks):
            return None
        try:
            best_bid = float(bids[0].get("px", 0) or 0)
            best_ask = float(asks[0].get("px", 0) or 0)
        except Exception:
            return None
        if best_bid <= 0 or best_ask <= 0:
            return None
        # cache along with spread bps to avoid recalculation
        mid = (float(best_bid) + float(best_ask)) / 2.0
        sbps = self._spread_bps(bid=float(best_bid), ask=float(best_ask), mid=float(mid)) or 0.0
        self._l2_cache_by_coin[coin] = (float(best_bid), float(best_ask), float(sbps))
        self._l2_cache_at_by_coin[coin] = now
        return float(best_bid), float(best_ask)

    def _spread_bps(self, *, bid: float, ask: float, mid: float) -> Optional[float]:
        if bid <= 0 or ask <= 0 or mid <= 0:
            return None
        if ask < bid:
            return None
        return (float(ask) - float(bid)) / float(mid) * 10000.0

    def _latest_open_fill_px_by_coin_side(self, fills: Any) -> Dict[str, Dict[str, float]]:
        """Build {coin: {B: px, A: px}} from leader fills, using the latest OPEN fill per side."""
        out: Dict[str, Dict[str, float]] = {}
        if not isinstance(fills, list):
            return out

        # Track latest time to pick newest fill per (coin, side)
        latest_ts: Dict[Tuple[str, str], int] = {}
        for f in fills:
            if not isinstance(f, dict):
                continue
            try:
                coin = str(f.get("coin", "") or "")
                side = str(f.get("side", "") or "")
                if not coin or side not in ("B", "A"):
                    continue
                px = float(f.get("px", 0) or 0)
                if px <= 0:
                    continue
                ts = int(f.get("time", 0) or 0)
                dir_text = str(f.get("dir", "") or "").strip().lower()
                if not dir_text.startswith("open"):
                    continue
            except Exception:
                continue

            key = (coin, side)
            prev = latest_ts.get(key, -1)
            if ts >= prev:
                latest_ts[key] = ts
                out.setdefault(coin, {})[side] = float(px)
        return out

    def _is_strict_better_vs_fill(self, *, is_buy: bool, mid: float, leader_fill_px: float) -> bool:
        """Strict better:
        - BUY: mid < leader_fill_px
        - SELL: mid > leader_fill_px
        """
        if leader_fill_px <= 0 or mid <= 0:
            return False
        return (float(mid) < float(leader_fill_px)) if is_buy else (float(mid) > float(leader_fill_px))

    def _is_price_favorable(self, *, is_buy: bool, mid: float, reference_entry_px: float, allow_worse_pct: float) -> bool:
        """Price gate: only trade when mid price is not worse than reference entry by allow_worse_pct.

        - BUY (increase long / cover short): favorable when mid <= ref * (1 + allow_worse_pct)
        - SELL (increase short / sell long): favorable when mid >= ref * (1 - allow_worse_pct)
        """
        if reference_entry_px <= 0 or mid <= 0:
            return True
        allow = max(0.0, float(allow_worse_pct))
        ref = float(reference_entry_px)
        if is_buy:
            return float(mid) <= ref * (1.0 + allow)
        return float(mid) >= ref * (1.0 - allow)

    def _chunk_sizes(
        self,
        *,
        total_size: float,
        price: float,
        sz_decimals: int,
        min_trade_size: float,
        max_notional_per_trade_usd: float,
        min_notional_usd: float,
    ) -> List[float]:
        remaining = float(abs(total_size))
        if remaining <= 0 or price <= 0:
            return []

        chunks: List[float] = []
        while remaining > 0:
            raw_size = remaining
            if max_notional_per_trade_usd and max_notional_per_trade_usd > 0:
                raw_size = min(raw_size, float(max_notional_per_trade_usd) / float(price))

            chunk = self._round_down(float(raw_size), int(sz_decimals))
            if chunk <= 0:
                break
            if chunk < float(min_trade_size):
                break
            if float(chunk) * float(price) < float(min_notional_usd):
                break

            chunks.append(float(chunk))
            remaining = max(0.0, remaining - float(chunk))

            # Avoid infinite loops from rounding.
            if remaining > 0 and remaining < (10 ** (-max(0, min(8, int(sz_decimals))))):
                break

        return chunks

    async def plan_ratio_sync(
        self,
        *,
        leader_address: str,
        copy_ratio: float,
        min_trade_size: float,
        max_notional_per_trade_usd: float,
        min_notional_usd: float,
        min_rel_diff: float,
        allow_worse_pct: float,
        gate_reductions: bool,
        price_ref_mode: str = "entry",  # "entry" | "strict_fill_open"
        fill_ref_fallback: str = "skip",  # "skip" | "entry"
        spread_gate_enabled: bool = False,
        max_spread_bps: float = 0.0,
        exclude_recent_trades: Optional[Dict[str, float]] = None,
        skip_recent_trade_s: float = 0.0,
    ) -> Dict[str, Any]:
        """Plan ratio-sync orders (does not execute)."""
        await self.update_positions(force=True)

        try:
            leader_state = await asyncio.to_thread(self.info.user_state, leader_address)
        except Exception as e:
            return {"status": "error", "reason": f"leader_user_state_failed: {e}", "orders": []}

        leader_positions = self._positions_from_user_state_with_entry(leader_state if isinstance(leader_state, dict) else {})
        mids = await self._get_mid_prices()

        leader_fill_px_by_coin_side: Dict[str, Dict[str, float]] = {}
        if str(price_ref_mode).strip().lower() == "strict_fill_open":
            leader_key = str(leader_address).lower()
            now = time.monotonic()
            cached_at = float(self._fills_cache_at_by_leader.get(leader_key, 0.0) or 0.0)
            cached = self._fills_cache_by_leader.get(leader_key)
            if cached and (now - cached_at) <= float(self._fills_cache_ttl_s):
                leader_fill_px_by_coin_side = cached
            else:
                try:
                    fills = await asyncio.to_thread(self.info.user_fills, leader_address)
                    leader_fill_px_by_coin_side = self._latest_open_fill_px_by_coin_side(fills)
                    if leader_fill_px_by_coin_side:
                        self._fills_cache_by_leader[leader_key] = leader_fill_px_by_coin_side
                        self._fills_cache_at_by_leader[leader_key] = now
                except Exception as e:
                    logger.warning(f"Failed to fetch leader fills for strict gating: {e}")

        coins = sorted(set(leader_positions.keys()) | set(self.positions.keys()))
        orders: List[SyncOrder] = []
        skipped: List[Dict[str, Any]] = []
        l2_cache: Dict[str, Dict[str, float]] = {}

        for coin in coins:
            leader_size = float(leader_positions.get(coin, {}).get("size", 0.0))
            leader_entry_px = float(leader_positions.get(coin, {}).get("entry_px", 0.0))
            leader_leverage = int(float(leader_positions.get(coin, {}).get("leverage", 1.0) or 1.0))

            follower_pos = self.get_position(coin)
            follower_size = float(follower_pos.size) if follower_pos else 0.0
            follower_entry_px = float(follower_pos.entry_price) if follower_pos else 0.0

            # If manually flattened, never rebuild via ratio-sync until leader is fully flat again.
            if str(coin) in self._manual_locked_since_by_coin:
                if abs(float(leader_size)) > 0:
                    skipped.append({"coin": str(coin), "reason": "manual_lock_until_leader_flat"})
                    continue
                # Leader is flat -> reset lock/cooldown for this coin.
                try:
                    self._manual_locked_since_by_coin.pop(str(coin), None)
                    self._manual_sync_cooldown_until_by_coin.pop(str(coin), None)
                    logger.warning("🔓 Manual lock cleared for %s (leader is flat)", str(coin))
                except Exception:
                    pass

            # Time-based cooldown (optional): skip any ratio-sync attempts for this coin.
            if self.is_ratio_sync_blocked(coin):
                skipped.append({"coin": str(coin), "reason": "manual_cooldown_active"})
                continue

            # Avoid fighting real-time: skip coins with very recent leader trades.
            try:
                if exclude_recent_trades and float(skip_recent_trade_s or 0.0) > 0:
                    last = exclude_recent_trades.get(str(coin))
                    if last is not None:
                        if (time.monotonic() - float(last)) <= float(skip_recent_trade_s):
                            skipped.append({"coin": str(coin), "reason": "recent_leader_trade"})
                            continue
            except Exception:
                pass

            expected = float(leader_size) * float(copy_ratio)
            mid = float(mids.get(coin, 0.0) or 0.0)
            if mid <= 0:
                continue

            # Ignore tiny diffs unless expected is near zero (then use notional threshold only).
            diff = expected - follower_size
            if diff == 0:
                continue

            rel = abs(diff) / abs(expected) if abs(expected) > 0 else 999.0
            if abs(expected) > 0 and rel < float(min_rel_diff):
                continue

            ref_entry = leader_entry_px if leader_entry_px > 0 else follower_entry_px

            # Determine required operations.
            want_sign = 1 if expected > 0 else (-1 if expected < 0 else 0)
            have_sign = 1 if follower_size > 0 else (-1 if follower_size < 0 else 0)

            # A: close-to-zero target
            ops: List[Tuple[str, float, Optional[bool], str]] = []
            if want_sign == 0:
                if have_sign != 0:
                    ops.append(("close", abs(follower_size), (have_sign < 0), "flatten"))
            # B: empty follower
            elif have_sign == 0:
                ops.append(("open", abs(expected), (want_sign > 0), "open_to_target"))
            # C: same side
            elif want_sign == have_sign:
                if abs(expected) > abs(follower_size):
                    ops.append(("open", abs(expected - follower_size), (want_sign > 0), "top_up"))
                elif abs(expected) < abs(follower_size):
                    # close reduces exposure; for gating decisions, close-long is SELL (is_buy=False),
                    # close-short is BUY (is_buy=True).
                    ops.append(("close", abs(follower_size - expected), (have_sign < 0), "reduce"))
            # D: flip
            else:
                ops.append(("close", abs(follower_size), (have_sign < 0), "flip_close"))
                ops.append(("open", abs(expected), (want_sign > 0), "flip_open"))

            for kind, total_size, is_buy, reason in ops:
                decimals = await self._get_sz_decimals(coin)
                chunks = self._chunk_sizes(
                    total_size=total_size,
                    price=mid,
                    sz_decimals=int(decimals),
                    min_trade_size=float(min_trade_size),
                    max_notional_per_trade_usd=float(max_notional_per_trade_usd),
                    min_notional_usd=float(min_notional_usd),
                )
                if not chunks:
                    continue

                for chunk in chunks:
                    notional = float(chunk) * float(mid)
                    # Gate by price when requested.
                    should_gate = True
                    if kind == "close" and not gate_reductions:
                        should_gate = False

                    # Optional spread gate (default OFF): skip when market is too wide.
                    if should_gate and bool(spread_gate_enabled) and float(max_spread_bps or 0.0) > 0:
                        cached = l2_cache.get(coin)
                        if cached is None:
                            ba = await self._get_best_bid_ask(coin)
                            if ba:
                                bid, ask = ba
                                sbps = self._spread_bps(bid=bid, ask=ask, mid=mid)
                                cached = {"bid": float(bid), "ask": float(ask), "spread_bps": float(sbps or 0.0)}
                            else:
                                cached = {"bid": 0.0, "ask": 0.0, "spread_bps": 0.0}
                            l2_cache[coin] = cached

                        sbps_val = float(cached.get("spread_bps", 0.0) or 0.0)
                        # If we cannot compute spread, be conservative: skip in spread-gated mode.
                        if sbps_val <= 0:
                            if str(self._spread_unavailable_action) != "ignore":
                                skipped.append(
                                    {
                                        "coin": coin,
                                        "kind": kind,
                                        "size": float(chunk),
                                        "price": float(mid),
                                        "reason": f"spread_unavailable:{reason}",
                                    }
                                )
                                continue

                        if sbps_val > float(max_spread_bps):
                            skipped.append(
                                {
                                    "coin": coin,
                                    "kind": kind,
                                    "size": float(chunk),
                                    "price": float(mid),
                                    "bid": float(cached.get("bid", 0.0) or 0.0),
                                    "ask": float(cached.get("ask", 0.0) or 0.0),
                                    "spread_bps": float(sbps_val),
                                    "max_spread_bps": float(max_spread_bps),
                                    "reason": f"spread_too_wide:{reason}",
                                }
                            )
                            continue

                    if should_gate and is_buy is not None:
                        mode = str(price_ref_mode).strip().lower()
                        ok = True
                        if mode == "strict_fill_open":
                            side = "B" if bool(is_buy) else "A"
                            fill_px = float(leader_fill_px_by_coin_side.get(coin, {}).get(side, 0.0) or 0.0)
                            ok = self._is_strict_better_vs_fill(is_buy=bool(is_buy), mid=float(mid), leader_fill_px=float(fill_px))
                            if (not ok) and str(fill_ref_fallback).strip().lower() == "entry":
                                ok = self._is_price_favorable(
                                    is_buy=bool(is_buy),
                                    mid=float(mid),
                                    reference_entry_px=float(ref_entry),
                                    allow_worse_pct=float(allow_worse_pct),
                                )
                            if (not ok) and float(self._strict_gate_max_wait_s or 0.0) > 0 and fill_px > 0:
                                key = (str(coin), side)
                                first = float(self._strict_gate_first_skip_at.get(key, 0.0) or 0.0)
                                now = time.monotonic()
                                if first <= 0:
                                    self._strict_gate_first_skip_at[key] = now
                                elif (now - first) >= float(self._strict_gate_max_wait_s):
                                    # After waiting long enough, relax to entryPx gating.
                                    ok = self._is_price_favorable(
                                        is_buy=bool(is_buy),
                                        mid=float(mid),
                                        reference_entry_px=float(ref_entry),
                                        allow_worse_pct=float(allow_worse_pct),
                                    )
                            if not ok:
                                try:
                                    key = (str(coin), side)
                                    if key not in self._strict_gate_first_skip_at and fill_px > 0:
                                        self._strict_gate_first_skip_at[key] = time.monotonic()
                                except Exception:
                                    pass
                                skipped.append(
                                    {
                                        "coin": coin,
                                        "kind": kind,
                                        "size": float(chunk),
                                        "price": float(mid),
                                        "leader_fill_px": float(fill_px),
                                        "fallback": str(fill_ref_fallback),
                                        "reason": f"strict_fill_not_better:{reason}",
                                    }
                                )
                                continue
                            # Clear strict-skip timer once eligible.
                            try:
                                key = (str(coin), side)
                                self._strict_gate_first_skip_at.pop(key, None)
                            except Exception:
                                pass
                        else:
                            ok = self._is_price_favorable(
                                is_buy=bool(is_buy),
                                mid=float(mid),
                                reference_entry_px=float(ref_entry),
                                allow_worse_pct=float(allow_worse_pct),
                            )
                            if not ok:
                                skipped.append(
                                    {
                                        "coin": coin,
                                        "kind": kind,
                                        "size": float(chunk),
                                        "price": float(mid),
                                        "reference_entry_px": float(ref_entry),
                                        "allow_worse_pct": float(allow_worse_pct),
                                        "reason": f"price_not_favorable:{reason}",
                                    }
                                )
                                continue

                    orders.append(
                        SyncOrder(
                            coin=str(coin),
                            kind=str(kind),
                            size=float(chunk),
                            is_buy=bool(is_buy) if is_buy is not None else None,
                            price=float(mid),
                            notional=float(notional),
                            reason=str(reason),
                            follower_before=float(follower_size),
                            expected=float(expected),
                            leader_entry_px=float(leader_entry_px),
                            reference_entry_px=float(ref_entry),
                            leader_leverage=int(leader_leverage),
                            sz_decimals=int(decimals),
                        )
                    )

        total_notional = sum(o.notional for o in orders)
        return {
            "status": "ok",
            "leader_address": str(leader_address),
            "copy_ratio": float(copy_ratio),
            "price_ref_mode": str(price_ref_mode),
            "fill_ref_fallback": str(fill_ref_fallback),
            "spread_gate_enabled": bool(spread_gate_enabled),
            "max_spread_bps": float(max_spread_bps or 0.0),
            "orders": orders,
            "orders_count": int(len(orders)),
            "total_notional": float(total_notional),
            "skipped": skipped,
            "skipped_count": int(len(skipped)),
        }

    async def execute_ratio_sync(
        self,
        *,
        leader_address: str,
        copy_ratio: float,
        min_trade_size: float,
        max_notional_per_trade_usd: float,
        min_notional_usd: float,
        min_rel_diff: float,
        allow_worse_pct: float,
        gate_reductions: bool,
        default_leverage: int,
        price_ref_mode: str = "entry",
        fill_ref_fallback: str = "skip",
        spread_gate_enabled: bool = False,
        max_spread_bps: float = 0.0,
        exclude_recent_trades: Optional[Dict[str, float]] = None,
        skip_recent_trade_s: float = 0.0,
    ) -> Dict[str, Any]:
        """Execute ratio-sync orders (price-gated)."""
        plan = await self.plan_ratio_sync(
            leader_address=leader_address,
            copy_ratio=copy_ratio,
            min_trade_size=min_trade_size,
            max_notional_per_trade_usd=max_notional_per_trade_usd,
            min_notional_usd=min_notional_usd,
            min_rel_diff=min_rel_diff,
            allow_worse_pct=allow_worse_pct,
            gate_reductions=gate_reductions,
            price_ref_mode=price_ref_mode,
            fill_ref_fallback=fill_ref_fallback,
            spread_gate_enabled=spread_gate_enabled,
            max_spread_bps=max_spread_bps,
            exclude_recent_trades=exclude_recent_trades,
            skip_recent_trade_s=skip_recent_trade_s,
        )
        if plan.get("status") != "ok":
            return plan

        orders: List[SyncOrder] = list(plan.get("orders") or [])
        if not orders:
            return {**plan, "exec_status": "noop", "submitted": 0, "errors": 0, "results": []}

        results: List[Dict[str, Any]] = []
        errors = 0
        submitted = 0

        for o in orders:
            lock = self._get_coin_lock(o.coin)
            await lock.acquire()
            try:
                if o.kind == "close":
                    # market_close reduces position regardless of side
                    closed = await self._market_close_partial(o.coin, float(o.size))
                    results.append({"coin": o.coin, "kind": o.kind, "size": float(o.size), "closed": float(closed or 0.0), "reason": o.reason})
                    submitted += 1
                    continue

                if o.kind == "open":
                    # Prefer leader leverage if present, bounded by default max.
                    lev = int(getattr(o, "leader_leverage", 0) or 0) or int(default_leverage)
                    if lev < 1:
                        lev = 1
                    await self._set_leverage(o.coin, lev)
                    await self._market_open(o.coin, bool(o.is_buy), float(o.size))
                    results.append({"coin": o.coin, "kind": o.kind, "size": float(o.size), "is_buy": bool(o.is_buy), "reason": o.reason})
                    submitted += 1
                    continue

                results.append({"coin": o.coin, "kind": o.kind, "size": float(o.size), "error": "unknown_kind"})
                errors += 1

            except Exception as e:
                errors += 1
                results.append({"coin": o.coin, "kind": o.kind, "size": float(o.size), "error": str(e)})
            finally:
                try:
                    lock.release()
                except Exception:
                    pass

        # Refresh lazily after submissions.
        try:
            self.schedule_refresh(delay_s=1.0)
        except Exception:
            pass

        return {**plan, "exec_status": "submitted", "submitted": int(submitted), "errors": int(errors), "results": results}
