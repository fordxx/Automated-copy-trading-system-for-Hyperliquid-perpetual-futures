"""Position Manager for Hyperliquid Copy Trader.

负责管理跟单账户的仓位。
"""
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import asyncio
import time

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


class PositionManager:
    """仓位管理器。

    管理跟单账户的仓位，执行开仓、平仓等操作。
    """

    def __init__(self, exchange_client: Exchange, info_client: Info):
        self.exchange = exchange_client
        self.info = info_client
        self.positions: Dict[str, Position] = {}
        self._last_positions_update = 0.0
        # In practice user_state is the most rate-limit-prone call; keep a conservative floor.
        self._min_positions_update_interval = 2.0

        # 429 backoff handling
        self._consecutive_429_errors = 0
        self._backoff_until = 0.0
        self._max_backoff_s = 120.0

        # Debounced refresh to avoid double-refresh per trade burst
        self._refresh_task: Optional[asyncio.Task] = None

        logger.info("✅ PositionManager initialized")

    async def update_positions(self):
        """更新当前仓位信息。"""
        try:
            now = time.monotonic()
            if now < self._backoff_until:
                return
            if (now - self._last_positions_update) < self._min_positions_update_interval:
                return

            # 获取账户仓位（最容易触发 429）
            account_positions = await asyncio.to_thread(self.info.user_state, self.exchange.account_address)

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

    async def execute_copy_trade(self, trade: MonitoredTrade, copy_ratio: float, max_size: float, max_leverage: int = 5):
        """执行跟单交易（极速开/平）。

        策略：
        - 优先使用 fill 的 side(B=买/A=卖) 来决定方向。
        - 如果方向与当前持仓相反，则优先 reduce/close（极速平仓）。
        - SDK 调用全部放到线程，避免阻塞 asyncio 事件循环。
        """
        try:
            copy_size = min(trade.size * copy_ratio, max_size)
            if copy_size < 0.01:
                logger.info(f"Copy size {copy_size} too small, skipping")
                return

            coin = trade.coin
            position = self.get_position(coin)

            side = getattr(trade, 'side', None)
            if side in ("B", "A"):
                is_buy = side == "B"
            else:
                is_buy = trade.action == TradeAction.OPEN_LONG

            leverage = int(getattr(trade, 'leverage', 1) or 1)
            leverage = max(1, min(leverage, int(max_leverage)))

            if is_buy and position and position.is_short:
                await self._market_close_partial(coin, copy_size)
            elif (not is_buy) and position and position.is_long:
                await self._market_close_partial(coin, copy_size)
            else:
                await self._set_leverage(coin, leverage)
                await self._market_open(coin, is_buy, copy_size)

            # Refresh positions lazily to avoid user_state bursts (and 429).
            self.schedule_refresh(delay_s=1.0)

        except Exception as e:
            logger.error(f"Error executing copy trade: {e}")

    async def _market_open(self, coin: str, is_buy: bool, size: float):
        try:
            result = await asyncio.to_thread(self.exchange.market_open, coin, is_buy, size)
            logger.info(f"Market open: {coin} {'BUY' if is_buy else 'SELL'} {size}, result: {result}")
        except Exception as e:
            logger.error(f"Error market_open {coin}: {e}")

    async def _market_close_partial(self, coin: str, size: float):
        try:
            position = self.get_position(coin)
            if not position or position.size == 0:
                logger.warning(f"No position to close for {coin}")
                return

            close_size = min(size, abs(position.size))
            result = await asyncio.to_thread(self.exchange.market_close, coin, close_size)
            logger.info(f"Market close: {coin} {close_size}, result: {result}")
        except Exception as e:
            logger.error(f"Error market_close {coin}: {e}")

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