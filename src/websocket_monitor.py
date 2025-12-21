"""WebSocket Monitor for Hyperliquid Copy Trader.

实时监控指定地址的交易，使用WebSocket推送实现零延迟。
"""
import asyncio
import logging
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.types import UserFillsSubscription

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Hyperliquid WebSocket 实时交易监控器。

    使用WebSocket订阅目标地址的fills，实现实时交易监控。
    """

    def __init__(self, target_address: str, use_testnet: bool = False,
                 exclude_addresses: List[str] = None,
                 on_trade_callback: Optional[Callable] = None,
                 on_ready_callback: Optional[Callable[[], Any]] = None):
        """初始化WebSocket监控器。

        Args:
            target_address: 要监控的目标地址
            use_testnet: 是否使用测试网
            exclude_addresses: 需要排除的地址列表
            on_trade_callback: 收到新交易时的回调函数
        """
        self.target_address = target_address.lower()
        self.exclude_addresses = [addr.lower() for addr in (exclude_addresses or [])]
        self.use_testnet = use_testnet
        self.on_trade_callback = on_trade_callback
        self.on_ready_callback = on_ready_callback

        # 保存配置，延迟初始化Info客户端
        base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
        self.base_url = base_url
        self.info_client = None  # 将在start()中初始化
        self._subscription_id = None

        # Heartbeat / reconnect settings
        self._last_message_time = time.monotonic()
        self._idle_timeout_s = 30.0
        self._reconnect_base_delay_s = 3.0
        self._reconnect_max_delay_s = 60.0
        self._reconnect_attempts = 0

        # 状态追踪
        self.last_check_timestamp = int(datetime.now().timestamp() * 1000)
        self.processed_tx_hashes = set()
        self.is_running = False
        self.snapshot_received = False
        self._ready_fired_for_connection = False

        # 统计信息
        self.stats = {
            'total_messages': 0,
            'snapshot_messages': 0,
            'streaming_messages': 0,
            'trades_detected': 0,
            'last_trade_time': None,
            'reconnects': 0,
            'last_connect_time': None,
            'last_reconnect_delay_s': None,
            'last_error': None,
        }

        logger.info(f"✅ WebSocketMonitor initialized for {target_address}")
        logger.info(f"📍 监控起始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"🌐 网络: {'Testnet' if use_testnet else 'Mainnet'}")

    async def start(self):
        """启动WebSocket监控。"""
        if self.is_running:
            logger.warning("WebSocket monitor is already running")
            return

        self.is_running = True
        logger.info("🚀 Starting WebSocket monitor...")

        while self.is_running:
            try:
                self.snapshot_received = False
                self._ready_fired_for_connection = False
                self._last_message_time = time.monotonic()

                # 初始化Info客户端（包含WebSocket连接）
                logger.info("Initializing WebSocket connection...")
                # Info() may spin up websocket internals; create it off the event loop to avoid blocking.
                self.info_client = await asyncio.to_thread(Info, base_url=self.base_url, skip_ws=False)

                # 给WebSocket一点时间建立连接
                await asyncio.sleep(0.5)

                subscription: UserFillsSubscription = {
                    "type": "userFills",
                    "user": self.target_address
                }

                logger.info(f"📡 Subscribing to userFills for {self.target_address}...")
                self._subscription_id = self.info_client.subscribe(subscription, self._handle_ws_message)
                logger.info(f"✅ Subscription ID: {self._subscription_id}")
                logger.info("✅ WebSocket subscription active - waiting for fills...")

                # Connection is live; reset reconnect backoff.
                self._reconnect_attempts = 0
                self.stats['last_connect_time'] = datetime.now()

                # Run until stopped or idle timeout triggers reconnect.
                while self.is_running:
                    await asyncio.sleep(1)
                    if self.snapshot_received:
                        idle_for = time.monotonic() - self._last_message_time
                        if idle_for >= self._idle_timeout_s:
                            raise RuntimeError(f"WebSocket idle for {idle_for:.1f}s, reconnecting")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"🔄 WebSocket monitor reconnect: {e}")
                self.stats['reconnects'] += 1
                self.stats['last_error'] = str(e)

                # Best-effort cleanup before reconnecting (do NOT flip is_running).
                await self._cleanup_connection()

                if self.is_running:
                    self._reconnect_attempts += 1
                    delay = min(
                        self._reconnect_base_delay_s * (2 ** max(0, self._reconnect_attempts - 1)),
                        self._reconnect_max_delay_s,
                    )
                    self.stats['last_reconnect_delay_s'] = delay
                    await asyncio.sleep(delay)

    async def _cleanup_connection(self):
        """Best-effort unsubscribe/cleanup without stopping the monitor.

        This is important for unstable networks: transient errors should not
        permanently stop monitoring; we just reconnect.
        """
        try:
            if not self.info_client:
                return

            subscription: UserFillsSubscription = {
                "type": "userFills",
                "user": self.target_address,
            }

            try:
                self.info_client.unsubscribe(subscription)
            except TypeError:
                if self._subscription_id is not None:
                    self.info_client.unsubscribe(self._subscription_id)
        except Exception:
            pass
        finally:
            self._subscription_id = None
            self.info_client = None

    async def stop(self):
        """停止WebSocket监控。"""
        logger.info("🛑 Stopping WebSocket monitor...")
        self.is_running = False

        # 取消订阅 / 清理连接
        await self._cleanup_connection()
        logger.info("✅ WebSocket stopped")

    def _handle_ws_message(self, message: Dict[str, Any]):
        """处理WebSocket消息。

        Args:
            message: WebSocket推送的消息
        """
        try:
            self._last_message_time = time.monotonic()
            self.stats['total_messages'] += 1

            # 检查是否是快照消息
            is_snapshot = message.get('isSnapshot', False)

            if is_snapshot:
                self.stats['snapshot_messages'] += 1
                self.snapshot_received = True
                logger.info(f"📸 Received snapshot with {len(message.get('fills', []))} fills")
                # 快照消息只用于初始化，不触发交易

                # Fire a one-time ready callback per connection so the owner can do
                # catch-up logic after reconnect (e.g., REST backfill with filters).
                if (not self._ready_fired_for_connection) and self.on_ready_callback:
                    self._ready_fired_for_connection = True
                    try:
                        asyncio.create_task(self._invoke_ready_callback())
                    except Exception:
                        pass
                return
            else:
                self.stats['streaming_messages'] += 1

            # 获取fills数据
            fills = message.get('fills', [])

            if not fills:
                return

            logger.info(f"⚡ Received {len(fills)} new fills from WebSocket")

            # 处理每个fill
            for fill in fills:
                self._process_fill(fill)

        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            logger.debug(f"Message content: {message}")

    def _process_fill(self, fill: Dict[str, Any]):
        """处理单个fill数据。

        Args:
            fill: fill数据字典
        """
        try:
            # 检查排除地址
            user = fill.get('user', '').lower()
            if user in self.exclude_addresses:
                logger.debug(f"Skipping fill from excluded address: {user}")
                return

            # 提取交易信息
            coin = fill.get('coin', 'Unknown')
            side = fill.get('side', 'Unknown')
            size = float(fill.get('sz', 0))
            price = float(fill.get('px', 0))
            timestamp = fill.get('time', 0)
            tx_hash = fill.get('hash', '')

            # 去重检查
            if tx_hash in self.processed_tx_hashes:
                return

            # 检查时间戳（只处理启动后的新交易）
            if timestamp <= self.last_check_timestamp:
                return

            # 标记为已处理
            self.processed_tx_hashes.add(tx_hash)
            self.stats['trades_detected'] += 1
            self.stats['last_trade_time'] = datetime.fromtimestamp(timestamp / 1000)

            # 解析交易动作
            from .trade_monitor import MonitoredTrade, TradeAction

            # 判断是开仓还是平仓
            # 注意：这里的逻辑可能需要结合当前仓位状态来判断
            # 暂时使用简化逻辑：买入=开多，卖出=开空或平多
            if side == 'B':
                action = TradeAction.OPEN_LONG
            else:
                action = TradeAction.OPEN_SHORT

            trade = MonitoredTrade(
                action=action,
                coin=coin,
                size=size,
                price=price,
                leverage=1,  # WebSocket数据中可能没有杠杆信息
                timestamp=timestamp,
                tx_hash=tx_hash,
                side=side
            )

            # 记录交易
            logger.info(f"🎯 NEW TRADE DETECTED: {coin} {side} {size} @ ${price:.2f}")
            logger.info(f"   Time: {self.stats['last_trade_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"   Hash: {tx_hash[:16]}...")

            # 触发回调
            if self.on_trade_callback:
                # 在异步上下文中调用回调
                asyncio.create_task(self._invoke_callback(trade))

        except Exception as e:
            logger.error(f"Error processing fill: {e}")
            logger.debug(f"Fill data: {fill}")

    async def _invoke_callback(self, trade):
        """异步调用交易回调。"""
        try:
            if asyncio.iscoroutinefunction(self.on_trade_callback):
                await self.on_trade_callback(trade)
            else:
                self.on_trade_callback(trade)
        except Exception as e:
            logger.error(f"Error in trade callback: {e}")

    async def _invoke_ready_callback(self):
        try:
            cb = self.on_ready_callback
            if cb is None:
                return

            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()
        except Exception as e:
            logger.error(f"Error in ready callback: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取监控统计信息。"""
        return {
            **self.stats,
            'is_running': self.is_running,
            'snapshot_received': self.snapshot_received,
            'processed_tx_count': len(self.processed_tx_hashes)
        }
