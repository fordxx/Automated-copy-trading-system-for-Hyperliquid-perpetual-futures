"""Trade Monitor for Hyperliquid Copy Trader.

负责监控指定地址的链上交易历史。
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import time

from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)


class TradeAction:
    """交易动作枚举。"""

    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    ADJUST_LEVERAGE = "adjust_leverage"


class MonitoredTrade:
    """监控到的交易信息。"""

    def __init__(
        self,
        action: str,
        coin: str,
        size: float,
        price: float,
        leverage: int,
        timestamp: int,
        tx_hash: str,
        direction: str = None
    ):
        self.action = action
        self.coin = coin
        self.size = size
        self.price = price
        self.leverage = leverage
        self.timestamp = timestamp
        self.tx_hash = tx_hash
        self.direction = direction or ("long" if action in [TradeAction.OPEN_LONG, TradeAction.CLOSE_LONG] else "short")

    def __repr__(self):
        return f"MonitoredTrade(action={self.action}, coin={self.coin}, size={self.size}, price={self.price})"


class TradeMonitor:
    """Hyperliquid 交易监控器。

    监控指定地址的链上交易历史，并解析交易动作。
    """

    def __init__(self, target_address: str, use_testnet: bool = False, exclude_addresses: List[str] = None):
        self.target_address = target_address.lower()
        self.exclude_addresses = [addr.lower() for addr in (exclude_addresses or [])]
        self.use_testnet = use_testnet

        base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
        self.info_client = Info(base_url=base_url)

        self.last_check_timestamp = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        self.processed_tx_hashes = set()

        logger.info(f"✅ TradeMonitor initialized for address {target_address} (testnet={use_testnet}, exclude={len(self.exclude_addresses)} addresses)")

    async def get_recent_trades(self) -> List[MonitoredTrade]:
        """获取目标地址的最近交易。

        Returns:
            解析后的交易列表
        """
        try:
            # 获取用户填充的订单（已成交的交易）
            user_fills = self.info_client.user_fills([self.target_address])

            if not user_fills:
                logger.debug(f"No fills found for address {self.target_address}")
                return []

            new_trades = []
            current_timestamp = int(time.time() * 1000)

            for fill in user_fills:
                # 检查是否是新交易
                tx_hash = fill.get("hash", "")
                if tx_hash in self.processed_tx_hashes:
                    continue

                # 解析交易
                trade = self._parse_fill_to_trade(fill)
                if trade:
                    new_trades.append(trade)
                    self.processed_tx_hashes.add(tx_hash)

                    # 更新最后检查时间戳
                    if trade.timestamp > self.last_check_timestamp:
                        self.last_check_timestamp = trade.timestamp

            logger.info(f"Found {len(new_trades)} new trades for address {self.target_address}")
            return new_trades

        except Exception as e:
            logger.error(f"Error getting recent trades: {e}")
            return []

    def _parse_fill_to_trade(self, fill: Dict[str, Any]) -> Optional[MonitoredTrade]:
        """解析填充数据为交易对象。

        Args:
            fill: Hyperliquid API 返回的填充数据

        Returns:
            解析后的交易对象，如果无法解析则返回 None
        """
        try:
            # 提取基本信息
            coin = fill.get("coin", "")
            size = float(fill.get("sz", 0))
            price = float(fill.get("px", 0))
            timestamp = int(fill.get("time", 0))
            tx_hash = fill.get("hash", "")
            side = fill.get("side", "")  # "B" for buy, "A" for sell
            leverage = int(fill.get("leverage", 1))

            if not all([coin, size > 0, price > 0, timestamp > 0]):
                logger.warning(f"Invalid fill data: {fill}")
                return None

            # 确定交易动作
            # 在 Hyperliquid 中，side "B" 表示买入（开多或平空），"A" 表示卖出（开空或平多）
            # 需要结合仓位信息来确定是开仓还是平仓
            # 这里简化处理，假设都是开仓操作
            if side == "B":
                action = TradeAction.OPEN_LONG
            elif side == "A":
                action = TradeAction.OPEN_SHORT
            else:
                logger.warning(f"Unknown side: {side}")
                return None

            return MonitoredTrade(
                action=action,
                coin=coin,
                size=size,
                price=price,
                leverage=leverage,
                timestamp=timestamp,
                tx_hash=tx_hash
            )

        except Exception as e:
            logger.error(f"Error parsing fill data: {e}, fill: {fill}")
            return None

    async def monitor_trades(self, callback: callable, poll_interval: int = 30):
        """持续监控交易并调用回调函数。

        Args:
            callback: 处理新交易的回调函数
            poll_interval: 轮询间隔（秒）
        """
        logger.info(f"Starting trade monitoring with {poll_interval}s interval")

        while True:
            try:
                trades = await self.get_recent_trades()
                if trades:
                    for trade in trades:
                        await callback(trade)

                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Error in trade monitoring loop: {e}")
                await asyncio.sleep(poll_interval)