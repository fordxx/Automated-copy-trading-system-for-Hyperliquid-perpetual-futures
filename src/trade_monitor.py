"""Trade Monitor for Hyperliquid Copy Trader.

负责监控指定地址的链上交易历史。
使用优化的轮询方式实现近实时监控。
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
        direction: str = None,
        side: str = None
    ):
        self.action = action
        self.coin = coin
        self.size = size
        self.price = price
        self.leverage = leverage
        self.timestamp = timestamp
        self.tx_hash = tx_hash
        self.side = side
        self.direction = direction or ("long" if action in [TradeAction.OPEN_LONG, TradeAction.CLOSE_LONG] else "short")

    def __repr__(self):
        return f"MonitoredTrade(action={self.action}, coin={self.coin}, size={self.size}, price={self.price})"


class TradeMonitor:
    """Hyperliquid 交易监控器。

    监控指定地址的链上交易历史，并解析交易动作。
    使用优化的轮询策略实现快速响应。
    """

    def __init__(self, target_address: str, use_testnet: bool = False, exclude_addresses: List[str] = None, min_api_interval: int = 300):
        self.target_address = target_address.lower()
        self.exclude_addresses = [addr.lower() for addr in (exclude_addresses or [])]
        self.use_testnet = use_testnet

        base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
        # REST-only: avoid starting SDK websocket internals.
        self.info_client = Info(base_url=base_url, skip_ws=True)

        # 初始化时间戳为当前时间，只监控启动后的新交易
        self.last_check_timestamp = int(datetime.now().timestamp() * 1000)
        self.processed_tx_hashes = set()

        # 性能优化：缓存最近的交易数据
        self._recent_trades_cache = []
        self._cache_timestamp = 0
        self._cache_duration = 500  # 0.5秒缓存，超高速响应
        self._force_refresh_interval = 2000  # 2秒强制刷新一次，确保不错过交易
        self._last_api_call = 0
        # min_api_interval is in milliseconds. Clamp to avoid API throttling.
        if min_api_interval < 1000:
            logger.warning(f"⚠️ min_api_interval too low ({min_api_interval}ms). Clamped to 1000ms to reduce rate limits")
            min_api_interval = 1000
        self._min_api_interval = min_api_interval  # 最小API调用间隔(ms)

        # 429错误处理
        self._rate_limit_backoff = 0  # 速率限制退避时间（秒）
        self._max_backoff = 300  # 最大退避时间（5分钟）
        self._consecutive_429_errors = 0  # 连续429错误计数

        logger.info(f"✅ TradeMonitor initialized for address {target_address} (testnet={use_testnet}, exclude={len(self.exclude_addresses)} addresses)")
        logger.info(f"📍 监控起始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 只跟随此时间之后的新交易")

    async def get_recent_trades(self) -> List[MonitoredTrade]:
        """获取目标地址的最近交易。

        使用优化的策略：缓存 + 增量更新
        Returns:
            解析后的交易列表
        """
        try:
            current_time = int(time.time() * 1000)
            current_time_s = time.time()  # Use consistent floating-point seconds for backoff

            # 检查是否处于速率限制退避期
            if self._rate_limit_backoff > 0:
                backoff_remaining = self._rate_limit_backoff - current_time_s
                if backoff_remaining > 0:
                    logger.debug(f"⏳ Rate limit backoff active, waiting {backoff_remaining:.1f}s more")
                    return []
                else:
                    # 退避期结束，重置
                    logger.info(f"✅ Rate limit backoff expired, resuming API calls")
                    self._rate_limit_backoff = 0

            # API调用频率限制：避免过于频繁的API调用
            time_since_last_call = current_time - self._last_api_call
            if time_since_last_call < self._min_api_interval and self._recent_trades_cache:
                # 在最小间隔内，直接返回缓存（可能为空）
                return []

            # 检查是否需要强制刷新（确保不错过交易）
            force_refresh = current_time - self._cache_timestamp >= self._force_refresh_interval

            # 检查缓存是否仍然有效
            if not force_refresh and current_time - self._cache_timestamp < self._cache_duration and self._recent_trades_cache:
                # 启动后台刷新任务（不阻塞当前响应）
                asyncio.create_task(self._background_refresh())
                
                # 使用缓存数据，过滤出新的交易
                new_trades = []
                for trade in self._recent_trades_cache:
                    # NOTE: Hyperliquid can emit multiple fills with the exact same millisecond
                    # timestamp (and even the same tx hash). Use >= and rely on the per-fill
                    # dedup key to avoid missing same-timestamp fills.
                    if trade.timestamp >= self.last_check_timestamp and trade.tx_hash not in self.processed_tx_hashes:
                        new_trades.append(trade)
                        self.processed_tx_hashes.add(trade.tx_hash)
                
                if new_trades:
                    logger.debug(f"⚡ Found {len(new_trades)} new trades from cache (ultra-fast)")
                    self.last_check_timestamp = max(trade.timestamp for trade in new_trades)
                    return new_trades
            
            # 获取最新的用户填充数据（并发优化）
            self._last_api_call = current_time  # 记录API调用时间
            user_fills = await asyncio.get_event_loop().run_in_executor(None, self.info_client.user_fills, self.target_address)

            if not user_fills:
                logger.debug(f"No fills found for address {self.target_address}")
                # 更新缓存时间戳，即使没有数据
                self._cache_timestamp = current_time
                return []

            new_trades = []
            all_recent_trades = []

            for fill in user_fills:
                # 检查排除地址
                if fill.get("user", "").lower() in self.exclude_addresses:
                    continue

                # 解析交易
                trade = self._parse_fill_to_trade(fill)
                if trade:
                    all_recent_trades.append(trade)
                    
                    # 检查是否是新交易
                    if trade.timestamp >= self.last_check_timestamp and trade.tx_hash not in self.processed_tx_hashes:
                        new_trades.append(trade)
                        self.processed_tx_hashes.add(trade.tx_hash)

            # 更新缓存
            self._recent_trades_cache = all_recent_trades
            self._cache_timestamp = current_time

            # 更新最后检查时间戳
            if new_trades:
                self.last_check_timestamp = max(trade.timestamp for trade in new_trades)
                logger.info(f"🎯 Found {len(new_trades)} new trades for {self.target_address}")

            # API调用成功，重置429错误计数
            self._consecutive_429_errors = 0

            return new_trades

        except Exception as e:
            # 检查是否是429错误
            error_str = str(e)
            if "429" in error_str or "Too Many Requests" in error_str:
                self._consecutive_429_errors += 1

                # 计算指数退避时间：2^n * 10秒，最多5分钟
                backoff_seconds = min(2 ** self._consecutive_429_errors * 10, self._max_backoff)
                self._rate_limit_backoff = (time.time() + backoff_seconds)

                logger.warning(f"⚠️ Rate limit (429) detected! Backing off for {backoff_seconds}s (attempt #{self._consecutive_429_errors})")
            else:
                logger.error(f"Error getting recent trades: {e}")

            return []

    async def _background_refresh(self):
        """后台刷新缓存数据，确保数据新鲜度。"""
        try:
            # 获取最新的用户填充数据
            user_fills = await asyncio.get_event_loop().run_in_executor(None, self.info_client.user_fills, self.target_address)
            
            if user_fills:
                all_recent_trades = []
                for fill in user_fills:
                    # 检查排除地址
                    if fill.get("user", "").lower() in self.exclude_addresses:
                        continue

                    # 解析交易
                    trade = self._parse_fill_to_trade(fill)
                    if trade:
                        all_recent_trades.append(trade)

                # 更新缓存
                self._recent_trades_cache = all_recent_trades
                self._cache_timestamp = int(time.time() * 1000)
                logger.debug("🔄 Background cache refreshed")
                
        except Exception as e:
            logger.debug(f"Background refresh failed: {e}")

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
            raw_hash = str(fill.get("hash", "") or "")
            tid = fill.get("tid", None)
            # IMPORTANT: `hash` is NOT unique per fill; one order can produce many fills
            # that share the same hash. Use (hash, tid) when possible.
            if tid is not None and raw_hash:
                tx_hash = f"{raw_hash}:{tid}"
            elif tid is not None:
                tx_hash = f"tid:{tid}"
            else:
                tx_hash = raw_hash
            side = fill.get("side", "")  # "B" for buy, "A" for sell
            leverage = int(fill.get("leverage", 1))

            # Hyperliquid fills often include a human-readable direction like:
            # "Open Long", "Open Short", "Close Long", "Close Short".
            dir_text = str(fill.get("dir", "") or "").strip().lower()

            if not all([coin, size > 0, price > 0, timestamp > 0]):
                logger.warning(f"Invalid fill data: {fill}")
                return None

            # 确定交易动作：优先使用 dir 字段，避免把“平仓/清仓”误判为“开反向仓”。
            if dir_text.startswith("open") and "long" in dir_text:
                action = TradeAction.OPEN_LONG
            elif dir_text.startswith("open") and "short" in dir_text:
                action = TradeAction.OPEN_SHORT
            elif dir_text.startswith("close") and "long" in dir_text:
                action = TradeAction.CLOSE_LONG
            elif dir_text.startswith("close") and "short" in dir_text:
                action = TradeAction.CLOSE_SHORT
            else:
                # Fallback: best-effort by side
                if side == "B":
                    action = TradeAction.OPEN_LONG
                elif side == "A":
                    action = TradeAction.OPEN_SHORT
                else:
                    logger.warning(f"Unknown side: {side}")
                    return None

            direction = "long" if action in (TradeAction.OPEN_LONG, TradeAction.CLOSE_LONG) else "short"

            return MonitoredTrade(
                action=action,
                coin=coin,
                size=size,
                price=price,
                leverage=leverage,
                timestamp=timestamp,
                tx_hash=tx_hash,
                direction=direction,
                side=side,
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
