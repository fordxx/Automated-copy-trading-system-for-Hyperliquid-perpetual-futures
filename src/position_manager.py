"""Position Manager for Hyperliquid Copy Trader.

负责管理跟单账户的仓位。
"""
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

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

        logger.info("✅ PositionManager initialized")

    async def update_positions(self):
        """更新当前仓位信息。"""
        try:
            # 获取账户仓位
            account_positions = self.info.user_state(self.exchange.account_address)

            if not account_positions or "assetPositions" not in account_positions:
                logger.debug("No positions found")
                self.positions = {}
                return

            new_positions = {}
            for pos_data in account_positions["assetPositions"]:
                coin = pos_data.get("coin", "")
                position_data = pos_data.get("position", {})

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
            logger.debug(f"Updated positions: {len(self.positions)} positions")

        except Exception as e:
            logger.error(f"Error updating positions: {e}")

    def get_position(self, coin: str) -> Optional[Position]:
        """获取指定币种的仓位。"""
        return self.positions.get(coin)

    async def execute_copy_trade(self, trade: MonitoredTrade, copy_ratio: float, max_size: float):
        """执行跟单交易。

        Args:
            trade: 监控到的交易
            copy_ratio: 跟单比例
            max_size: 最大仓位大小
        """
        try:
            # 计算跟单大小
            copy_size = min(trade.size * copy_ratio, max_size)

            if copy_size < 0.01:  # 最小交易大小
                logger.info(f"Copy size {copy_size} too small, skipping")
                return

            logger.info(f"Executing copy trade: {trade.action} {copy_size} {trade.coin} at ratio {copy_ratio}")

            if trade.action == TradeAction.OPEN_LONG:
                await self._open_long(trade.coin, copy_size, trade.leverage)
            elif trade.action == TradeAction.OPEN_SHORT:
                await self._open_short(trade.coin, copy_size, trade.leverage)
            elif trade.action == TradeAction.CLOSE_LONG:
                await self._close_long(trade.coin, copy_size)
            elif trade.action == TradeAction.CLOSE_SHORT:
                await self._close_short(trade.coin, copy_size)

        except Exception as e:
            logger.error(f"Error executing copy trade: {e}")

    async def _open_long(self, coin: str, size: float, leverage: int):
        """开多仓。"""
        try:
            # 设置杠杆
            await self._set_leverage(coin, leverage)

            # 下单
            order_result = self.exchange.order(
                coin=coin,
                is_buy=True,
                sz=size,
                limit_px=None,  # 市价单
                order_type={"limit": {"tif": "Ioc"}}  # IOC 订单
            )

            logger.info(f"Opened long position: {coin} {size} @ leverage {leverage}, order: {order_result}")

        except Exception as e:
            logger.error(f"Error opening long position: {e}")

    async def _open_short(self, coin: str, size: float, leverage: int):
        """开空仓。"""
        try:
            # 设置杠杆
            await self._set_leverage(coin, leverage)

            # 下单
            order_result = self.exchange.order(
                coin=coin,
                is_buy=False,
                sz=size,
                limit_px=None,  # 市价单
                order_type={"limit": {"tif": "Ioc"}}  # IOC 订单
            )

            logger.info(f"Opened short position: {coin} {size} @ leverage {leverage}, order: {order_result}")

        except Exception as e:
            logger.error(f"Error opening short position: {e}")

    async def _close_long(self, coin: str, size: float):
        """平多仓。"""
        try:
            position = self.get_position(coin)
            if not position or not position.is_long:
                logger.warning(f"No long position to close for {coin}")
                return

            close_size = min(size, abs(position.size))

            order_result = self.exchange.order(
                coin=coin,
                is_buy=False,  # 卖出平多
                sz=close_size,
                limit_px=None,
                order_type={"limit": {"tif": "Ioc"}}
            )

            logger.info(f"Closed long position: {coin} {close_size}, order: {order_result}")

        except Exception as e:
            logger.error(f"Error closing long position: {e}")

    async def _close_short(self, coin: str, size: float):
        """平空仓。"""
        try:
            position = self.get_position(coin)
            if not position or not position.is_short:
                logger.warning(f"No short position to close for {coin}")
                return

            close_size = min(size, abs(position.size))

            order_result = self.exchange.order(
                coin=coin,
                is_buy=True,  # 买入平空
                sz=close_size,
                limit_px=None,
                order_type={"limit": {"tif": "Ioc"}}
            )

            logger.info(f"Closed short position: {coin} {close_size}, order: {order_result}")

        except Exception as e:
            logger.error(f"Error closing short position: {e}")

    async def _set_leverage(self, coin: str, leverage: int):
        """设置杠杆。"""
        try:
            self.exchange.update_leverage(coin, leverage)
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