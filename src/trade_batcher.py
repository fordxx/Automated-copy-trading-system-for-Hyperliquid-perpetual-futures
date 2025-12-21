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
    ):
        self._window_s = float(window_s)
        self._on_batch = on_batch

        self._queue: asyncio.Queue[MonitoredTrade] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
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
        per_coin: Dict[str, Dict[str, object]] = {}

        for t in trades:
            coin = t.coin
            side = getattr(t, "side", None)
            if side not in ("B", "A"):
                # Fallback to action
                side = "B" if t.action == TradeAction.OPEN_LONG else "A"

            signed = float(t.size) if side == "B" else -float(t.size)

            entry = per_coin.get(coin)
            if entry is None:
                per_coin[coin] = {
                    "net": signed,
                    "last": t,
                    "max_leverage": int(getattr(t, "leverage", 1) or 1),
                }
            else:
                entry["net"] = float(entry["net"]) + signed
                entry["last"] = t
                entry["max_leverage"] = max(int(entry["max_leverage"]), int(getattr(t, "leverage", 1) or 1))

        now_ms = int(time.time() * 1000)
        out: List[MonitoredTrade] = []

        for coin, entry in per_coin.items():
            net = float(entry["net"])
            if abs(net) <= 0:
                continue

            side = "B" if net > 0 else "A"
            action = TradeAction.OPEN_LONG if side == "B" else TradeAction.OPEN_SHORT

            last: MonitoredTrade = entry["last"]  # type: ignore[assignment]
            leverage = int(entry["max_leverage"])

            out.append(
                MonitoredTrade(
                    action=action,
                    coin=coin,
                    size=abs(net),
                    price=float(getattr(last, "price", 0) or 0),
                    leverage=leverage,
                    timestamp=now_ms,
                    tx_hash=f"batch:{now_ms}:{coin}:{side}",
                    side=side,
                )
            )

        return out
