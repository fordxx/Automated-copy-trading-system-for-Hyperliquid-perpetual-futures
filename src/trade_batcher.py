"""Burst trade batching for Hyperliquid Copy Trader.

Goal: reduce rate limits (429) and order spam when the followed address
opens/closes many orders in a short time.

We batch fills in a short window and net them per coin by side:
- BUY (B) contributes +size
- SELL (A) contributes -size

Then we emit at most one aggregated trade per coin per window.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Dict, List, Optional

from .trade_monitor import MonitoredTrade, TradeAction


class TradeBatcher:
    def __init__(
        self,
        *,
        window_s: float = 0.5,
        on_batch: Callable[[List[MonitoredTrade]], Awaitable[None]],
        max_queue_size: int = 10000,
    ):
        self._window_s = float(window_s)
        self._on_batch = on_batch

        self._queue: asyncio.Queue[MonitoredTrade] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: Optional[asyncio.Task] = None
        self._worker_lock = asyncio.Lock()
        self._closed = False

        self._stats: Dict[str, object] = {
            "submitted": 0,
            "dropped": 0,
            "batches": 0,
            "emitted": 0,
            "last_batch_size": 0,
            "last_emit_count": 0,
        }

    def submit(self, trade: MonitoredTrade) -> None:
        """Submit a trade for batching.

        This method is intentionally non-async for ease of calling from callbacks.
        """
        if self._closed:
            return

        self._stats["submitted"] = int(self._stats["submitted"]) + 1
        try:
            self._queue.put_nowait(trade)
        except asyncio.QueueFull:
            self._stats["dropped"] = int(self._stats["dropped"]) + 1
            return

        # Ensure only one worker task is created using a lock
        if self._worker_task is None or self._worker_task.done():
            # Create a task to acquire the lock and start worker if needed
            asyncio.create_task(self._ensure_worker_running())

    async def _ensure_worker_running(self) -> None:
        """Ensure only one worker task is running at a time."""
        async with self._worker_lock:
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._worker())

    async def close(self) -> None:
        self._closed = True
        task = self._worker_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def get_stats(self) -> Dict[str, object]:
        return dict(self._stats)

    async def _worker(self) -> None:
        while not self._closed:
            first = await self._queue.get()
            batch: List[MonitoredTrade] = [first]

            # Batch window: accumulate additional trades for a short time.
            await asyncio.sleep(self._window_s)

            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            self._stats["last_batch_size"] = len(batch)
            aggregated = self._aggregate(batch)

            self._stats["batches"] = int(self._stats["batches"]) + 1
            self._stats["last_emit_count"] = len(aggregated)
            self._stats["emitted"] = int(self._stats["emitted"]) + len(aggregated)

            if aggregated:
                await self._on_batch(aggregated)

    def _aggregate(self, trades: List[MonitoredTrade]) -> List[MonitoredTrade]:
        # IMPORTANT: do not net OPEN and CLOSE semantics together.
        # If the leader is closing (clearing) but the follower has no position,
        # an accidental OPEN would be dangerous. We therefore aggregate per
        # (coin, action) and preserve action on emission.
        per_key: Dict[tuple[str, str], Dict[str, object]] = {}
        coin_order: List[str] = []

        for t in trades:
            coin = t.coin
            if coin not in coin_order:
                coin_order.append(coin)
            action = str(getattr(t, "action", "") or "")
            if action not in (
                TradeAction.OPEN_LONG,
                TradeAction.OPEN_SHORT,
                TradeAction.CLOSE_LONG,
                TradeAction.CLOSE_SHORT,
            ):
                # Fallback: infer opens from side
                side = getattr(t, "side", None)
                if side == "B":
                    action = TradeAction.OPEN_LONG
                elif side == "A":
                    action = TradeAction.OPEN_SHORT
                else:
                    # If we can't infer, drop it from aggregation.
                    continue

            key = (coin, action)
            entry = per_key.get(key)
            if entry is None:
                per_key[key] = {
                    "sum_size": float(t.size),
                    "last": t,
                    "max_leverage": int(getattr(t, "leverage", 1) or 1),
                }
            else:
                entry["sum_size"] = float(entry["sum_size"]) + float(t.size)
                entry["last"] = t
                entry["max_leverage"] = max(int(entry["max_leverage"]), int(getattr(t, "leverage", 1) or 1))

        now_ms = int(time.time() * 1000)
        out: List[MonitoredTrade] = []

        # Stronger guarantee: for each coin, emit CLOSEs before OPENs (reduces risk of flipping/overlap).
        priority = {
            TradeAction.CLOSE_LONG: 0,
            TradeAction.CLOSE_SHORT: 0,
            TradeAction.OPEN_LONG: 1,
            TradeAction.OPEN_SHORT: 1,
        }

        for coin in coin_order:
            actions = [a for (c, a) in per_key.keys() if c == coin]
            actions.sort(key=lambda a: priority.get(a, 9))
            for action in actions:
                entry = per_key.get((coin, action))
                if not entry:
                    continue
                total_size = float(entry["sum_size"])
                if total_size <= 0:
                    continue

                # Preserve side semantics for downstream execution.
                if action in (TradeAction.OPEN_LONG, TradeAction.CLOSE_SHORT):
                    side = "B"
                else:
                    side = "A"

                last: MonitoredTrade = entry["last"]  # type: ignore[assignment]
                leverage = int(entry["max_leverage"])
                direction = "long" if action in (TradeAction.OPEN_LONG, TradeAction.CLOSE_LONG) else "short"

                out.append(
                    MonitoredTrade(
                        action=action,
                        coin=coin,
                        size=total_size,
                        price=float(getattr(last, "price", 0) or 0),
                        leverage=leverage,
                        timestamp=now_ms,
                        tx_hash=f"batch:{now_ms}:{coin}:{action}",
                        direction=direction,
                        side=side,
                    )
                )

        return out
