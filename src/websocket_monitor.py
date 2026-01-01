"""WebSocket Monitor for Hyperliquid Copy Trader.

实时监控指定地址的交易，使用WebSocket推送实现零延迟。
"""
import asyncio
from collections import deque
import logging
import json
import os
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

        # SDK callbacks may run on a non-async thread. Capture the main asyncio
        # loop in start() and schedule callbacks thread-safely.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 保存配置，延迟初始化Info客户端
        base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
        self.base_url = base_url
        self.info_client = None  # 将在start()中初始化
        self._subscription_id = None

        # Heartbeat / reconnect settings
        self._last_message_time = time.monotonic()
        # If no WS message arrives for this long, we reconnect.
        # Making this configurable helps reduce "idle reconnect" log spam when the
        # target address is simply inactive.
        self._idle_timeout_s = float(os.getenv('WEBSOCKET_IDLE_TIMEOUT_S', '30'))
        # Throttle the repetitive idle reconnect warning.
        self._idle_reconnect_log_interval_s = float(os.getenv('WEBSOCKET_IDLE_LOG_INTERVAL_S', '300'))
        self._last_idle_reconnect_log_at = 0.0
        self._reconnect_base_delay_s = 3.0
        self._reconnect_max_delay_s = 60.0
        self._reconnect_attempts = 0

        # 状态追踪
        # NOTE: Initialize to 0 so catch-up can use the full CATCHUP_WINDOW_S
        # on first connection. After that, this will be updated to the latest trade timestamp.
        self.last_check_timestamp = 0
        self.processed_tx_hashes = set()
        self._processed_tx_order: deque[str] = deque()
        self._max_dedup_set_size = int(os.getenv('WS_DEDUP_SET_SIZE', '10000') or 10000)
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
        logger.info(
            f"🔧 WS idle reconnect: timeout={self._idle_timeout_s:g}s, log_interval={self._idle_reconnect_log_interval_s:g}s"
        )

    async def start(self):
        """启动WebSocket监控。"""
        if self.is_running:
            logger.warning("WebSocket monitor is already running")
            return

        # Capture the loop that owns this monitor so we can schedule work from
        # SDK callback threads safely.
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

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
                # NOTE: We accept idle connections for extended periods when the target
                # address is simply not trading. Idle timeout protects against stuck sockets
                # but should be set high enough to avoid reconnect spam.
                while self.is_running:
                    await asyncio.sleep(1)
                    idle_for = time.monotonic() - self._last_message_time
                    if idle_for >= self._idle_timeout_s:
                        # Reconnect even if we never parsed a snapshot. This protects against
                        # message-shape mismatches, stuck sockets, and transient network stalls.
                        raise RuntimeError(f"WebSocket idle for {idle_for:.1f}s, reconnecting")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                msg = str(e)
                if 'WebSocket idle for' in msg:
                    now = time.monotonic()
                    if now - self._last_idle_reconnect_log_at >= self._idle_reconnect_log_interval_s:
                        self._last_idle_reconnect_log_at = now
                        logger.warning(f"🔄 WebSocket monitor reconnect: {e}")
                    else:
                        logger.debug(f"🔄 WebSocket monitor reconnect: {e}")
                else:
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

        # Clear loop reference (monitor is stopping)
        self._loop = None

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

            # SDK callbacks are not consistent across versions:
            # - dict: {channel: ..., data: {...}}
            # - dict: {isSnapshot: ..., fills: [...]}
            # - str/bytes: JSON-encoded message
            payload: Any = self._normalize_ws_payload(message)
            if not isinstance(payload, dict):
                return

            # 检查是否是快照消息
            is_snapshot = bool(payload.get('isSnapshot', False))

            if is_snapshot:
                self.stats['snapshot_messages'] += 1
                self.snapshot_received = True
                fills_for_log = payload.get('fills', [])
                if isinstance(fills_for_log, dict):
                    fills_for_log = [fills_for_log]
                if not isinstance(fills_for_log, list):
                    fills_for_log = []
                logger.info(f"📸 Received snapshot with {len(fills_for_log)} fills")
                # 快照消息只用于初始化，不触发交易

                # Fire a one-time ready callback per connection so the owner can do
                # catch-up logic after reconnect (e.g., REST backfill with filters).
                if (not self._ready_fired_for_connection) and self.on_ready_callback:
                    self._ready_fired_for_connection = True
                    try:
                        self._schedule_coroutine(self._invoke_ready_callback())
                    except Exception:
                        pass
                return
            else:
                self.stats['streaming_messages'] += 1

            # 获取fills数据
            fills: Any = payload.get('fills', payload.get('fill', []))
            if isinstance(fills, dict):
                fills = [fills]
            if not isinstance(fills, list):
                fills = []

            if not fills:
                return

            logger.info(f"⚡ Received {len(fills)} new fills from WebSocket")

            # Some payloads include the user at the envelope level instead of per-fill.
            default_user = payload.get('user', '') if isinstance(payload.get('user', ''), str) else ''

            # 处理每个fill
            for fill in fills:
                if isinstance(fill, dict):
                    self._process_fill(fill, default_user=default_user)

        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            logger.debug(f"Message content: {message}")

    def _normalize_ws_payload(self, message: Any) -> Any:
        """Normalize SDK callback payload into a dict when possible.

        The Hyperliquid Python SDK may emit dicts or raw JSON strings/bytes.
        This function best-effort parses/unwraps without throwing.
        """
        try:
            payload: Any = message

            # bytes/bytearray -> decode
            if isinstance(payload, (bytes, bytearray)):
                try:
                    payload = payload.decode('utf-8', errors='ignore')
                except Exception:
                    return None

            # str -> json
            if isinstance(payload, str):
                s = payload.strip()
                if s.startswith('{') or s.startswith('['):
                    try:
                        payload = json.loads(s)
                    except Exception:
                        return None
                else:
                    return None

            # dict envelope -> unwrap data when present
            if isinstance(payload, dict):
                inner = payload.get('data')
                # Sometimes 'data' itself is a JSON string.
                if isinstance(inner, (bytes, bytearray)):
                    try:
                        inner = inner.decode('utf-8', errors='ignore')
                    except Exception:
                        inner = None
                if isinstance(inner, str):
                    try:
                        inner = json.loads(inner)
                    except Exception:
                        inner = None
                if isinstance(inner, dict):
                    return inner
                return payload

            return payload
        except Exception:
            return None

    def _process_fill(self, fill: Dict[str, Any], default_user: str = ''):
        """处理单个fill数据。

        Args:
            fill: fill数据字典
        """
        try:
            # 检查排除地址
            user_val = fill.get('user')
            if not isinstance(user_val, str) or not user_val:
                user_val = default_user
            user = user_val.lower() if isinstance(user_val, str) else ''
            if user in self.exclude_addresses:
                logger.debug(f"Skipping fill from excluded address: {user}")
                return

            # 提取交易信息
            coin = fill.get('coin', 'Unknown')
            side = fill.get('side', 'Unknown')
            size = float(fill.get('sz', 0) or 0)
            price = float(fill.get('px', 0) or 0)
            timestamp = int(fill.get('time', fill.get('timestamp', 0)) or 0)

            # Normalize timestamp to milliseconds.
            # REST fills use ms; some WS payloads may use seconds.
            if 0 < timestamp < 10_000_000_000:
                timestamp *= 1000
            elif timestamp > 10_000_000_000_000:
                # Defensive: if we ever see microseconds/nanoseconds.
                timestamp = int(timestamp / 1000)

            # Dedup key MUST be unique per fill.
            # Hyperliquid often emits many partial fills for one order that share the same `hash`
            # (and even the same millisecond timestamp). Use (hash, tid) when possible.
            raw_hash = fill.get('hash') or fill.get('txHash') or ''
            if not isinstance(raw_hash, str):
                raw_hash = str(raw_hash)
            tid = fill.get('tid', None)

            if tid is not None and raw_hash:
                tx_hash = f"{raw_hash}:{tid}"
            elif tid is not None:
                tx_hash = f"tid:{tid}"
            else:
                tx_hash = raw_hash

            if not tx_hash:
                tx_hash = f"{user}:{coin}:{side}:{size}:{price}:{timestamp}"

            # 去重检查
            if tx_hash in self.processed_tx_hashes:
                return

            # 检查时间戳（只处理启动后的新交易）
            # Use < (not <=) so same-millisecond fills aren't dropped.
            if timestamp < self.last_check_timestamp:
                return

            # 标记为已处理（FIFO上限）
            if tx_hash not in self.processed_tx_hashes:
                self.processed_tx_hashes.add(tx_hash)
                self._processed_tx_order.append(tx_hash)
                while len(self._processed_tx_order) > self._max_dedup_set_size:
                    old = self._processed_tx_order.popleft()
                    self.processed_tx_hashes.discard(old)
            self.stats['trades_detected'] += 1
            self.stats['last_trade_time'] = datetime.fromtimestamp(timestamp / 1000)
            self.last_check_timestamp = max(self.last_check_timestamp, timestamp)

            # 解析交易动作
            from .trade_monitor import MonitoredTrade, TradeAction

            # Prefer the API-provided direction field when present to avoid
            # misclassifying CLOSE/clear trades as opens.
            dir_text = str(fill.get('dir', '') or '').strip().lower()
            if dir_text.startswith('open') and 'long' in dir_text:
                action = TradeAction.OPEN_LONG
            elif dir_text.startswith('open') and 'short' in dir_text:
                action = TradeAction.OPEN_SHORT
            elif dir_text.startswith('close') and 'long' in dir_text:
                action = TradeAction.CLOSE_LONG
            elif dir_text.startswith('close') and 'short' in dir_text:
                action = TradeAction.CLOSE_SHORT
            else:
                # Fallback: buy->open long, sell->open short
                action = TradeAction.OPEN_LONG if side == 'B' else TradeAction.OPEN_SHORT

            direction = 'long' if action in (TradeAction.OPEN_LONG, TradeAction.CLOSE_LONG) else 'short'

            lev_val = fill.get('leverage', 1)
            try:
                leverage = int(lev_val)
            except Exception:
                leverage = 1

            trade = MonitoredTrade(
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

            # 记录交易
            logger.info(f"🎯 NEW TRADE DETECTED: {coin} {side} {size} @ ${price:.2f}")
            logger.info(f"   Time: {self.stats['last_trade_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            display_hash = raw_hash or tx_hash
            logger.info(f"   Hash: {display_hash[:16]}...")

            # 触发回调
            if self.on_trade_callback:
                # SDK callback may not run on an asyncio loop thread.
                self._schedule_coroutine(self._invoke_callback(trade))

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

    def _schedule_coroutine(self, coro: Any) -> None:
        """Schedule a coroutine onto the captured asyncio loop.

        Hyperliquid SDK may invoke callbacks from a background thread with no
        running event loop. In that case, asyncio.create_task() would fail.
        """
        loop = self._loop
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(coro, loop)

            def _done(f):
                try:
                    f.result()
                except Exception as e:
                    logger.error(f"Scheduled coroutine failed: {e}")

            fut.add_done_callback(_done)
            return

        # Fallback: try to get current running loop
        try:
            current_loop = asyncio.get_running_loop()
            if current_loop.is_running():
                asyncio.create_task(coro)
                return
        except RuntimeError:
            pass

        # If no loop is available, try to get any event loop
        try:
            fallback_loop = asyncio.get_event_loop()
            if fallback_loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, fallback_loop)
                return
        except Exception:
            pass

        # Last resort: close the coroutine to prevent warnings
        try:
            coro.close()
        except Exception:
            pass
        logger.error(f"Cannot schedule coroutine (no running event loop available). Trade callback may be lost!")

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
