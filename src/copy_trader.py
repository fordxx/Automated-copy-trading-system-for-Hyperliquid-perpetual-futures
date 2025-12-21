"""Main Copy Trader implementation for Hyperliquid.

整合交易监控和仓位管理，实现自动跟单功能。
"""
import asyncio
import logging
import signal
import sys
import time
from typing import Dict, Any, Optional
import yaml
import os
from dotenv import load_dotenv
import secrets

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .trade_monitor import TradeMonitor, MonitoredTrade
from .websocket_monitor import WebSocketMonitor
from .position_manager import PositionManager
from .notifications import NotificationManager
from .trade_batcher import TradeBatcher

logger = logging.getLogger(__name__)


class HyperliquidCopyTrader:
    """Hyperliquid 自动跟单交易器。

    监控指定地址的交易并自动复制到自己的账户。
    """

    def __init__(self, config_path: Optional[str] = None):
        # Load environment variables
        load_dotenv()

        self.config = self._load_config(config_path)
        self.running = False

        # 初始化组件
        self.trade_monitor: Optional[TradeMonitor] = None
        self.ws_monitor: Optional[WebSocketMonitor] = None
        self.position_manager: Optional[PositionManager] = None
        self.notification_manager: Optional[NotificationManager] = None

        # WebSocket模式标志
        self.use_websocket = os.getenv('USE_WEBSOCKET', 'true').lower() == 'true'

        # Burst batching: reduces 429s and order spam when the target opens/closes many trades.
        batch_window_ms = float(os.getenv('TRADE_BATCH_WINDOW_MS', '500'))
        self._trade_batcher = TradeBatcher(window_s=batch_window_ms / 1000.0, on_batch=self._handle_trade_batch)

        # Reconnect catch-up (optional): after WS reconnect, backfill a bounded window via REST,
        # but only if the current price is strictly better than the original fill.
        self._catchup_enabled = os.getenv('CATCHUP_ENABLED', 'true').lower() == 'true'
        self._catchup_window_s = float(os.getenv('CATCHUP_WINDOW_S', '600'))
        self._catchup_max_trades = int(os.getenv('CATCHUP_MAX_TRADES', '200'))
        self._catchup_min_interval_s = float(os.getenv('CATCHUP_MIN_INTERVAL_S', '30'))
        self._catchup_start_delay_s = float(os.getenv('CATCHUP_START_DELAY_S', '0'))
        self._last_catchup_at = 0.0
        self._catchup_task: Optional[asyncio.Task] = None

        # Operator-in-the-loop approval (Telegram): ask before replaying catch-up trades.
        self._catchup_require_approval = os.getenv('CATCHUP_REQUIRE_APPROVAL', 'false').lower() == 'true'
        self._catchup_approval_timeout_s = float(os.getenv('CATCHUP_APPROVAL_TIMEOUT_S', '900'))
        self._catchup_second_confirm_timeout_s = float(os.getenv('CATCHUP_SECOND_CONFIRM_TIMEOUT_S', str(int(self._catchup_approval_timeout_s))))
        self._catchup_approval_poll_s = float(os.getenv('CATCHUP_APPROVAL_POLL_S', '2'))
        self._catchup_replay_spacing_s = float(os.getenv('CATCHUP_REPLAY_SPACING_S', '2'))
        self._tg_update_offset: Optional[int] = None

        # 初始化 Hyperliquid 客户端
        self._init_hyperliquid_clients()

        # 初始化通知管理器
        self._init_notifications()

        # 状态通知限制（避免频繁发送Telegram消息）
        # 需求：有开/平仓会走交易通知；状态推送仅在“有仓位”时周期发送。
        self._last_status_notification = 0.0
        self._status_notify_only_when_positions = os.getenv('STATUS_NOTIFY_ONLY_WHEN_POSITIONS', 'true').lower() == 'true'
        self._status_notification_interval = float(os.getenv('STATUS_NOTIFICATION_INTERVAL_S', '1800'))  # 默认 30 分钟

        logger.info("✅ HyperliquidCopyTrader initialized")

    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """加载配置文件，支持环境变量覆盖。"""
        config = {}

        # 如果提供了配置文件路径，先加载YAML配置
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            logger.info(f"Loaded config from {config_path}")

        # 从环境变量加载配置，覆盖YAML配置
        config = self._load_config_from_env(config)

        return config

    def _load_config_from_env(self, base_config: Dict[str, Any]) -> Dict[str, Any]:
        """从环境变量加载配置。"""
        config = base_config.copy()

        # Target trading configuration
        config['target_address'] = os.getenv('TARGET_ADDRESS', config.get('target_address', ''))
        exclude_addresses_str = os.getenv('EXCLUDE_ADDRESSES', '')
        if exclude_addresses_str:
            config['exclude_addresses'] = [addr.strip() for addr in exclude_addresses_str.split(',')]
        else:
            config['exclude_addresses'] = config.get('exclude_addresses', [])

        # Hyperliquid configuration
        if 'hyperliquid' not in config:
            config['hyperliquid'] = {}

        config['hyperliquid']['account_address'] = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS',
                                                            config['hyperliquid'].get('account_address', ''))
        config['hyperliquid']['private_key'] = os.getenv('HYPERLIQUID_PRIVATE_KEY',
                                                        config['hyperliquid'].get('private_key', ''))
        config['hyperliquid']['vault_address'] = os.getenv('HYPERLIQUID_VAULT_ADDRESS',
                                                          config['hyperliquid'].get('vault_address', ''))

        # Environment setting
        env_str = os.getenv('HYPERLIQUID_ENV', 'mainnet').lower()
        config['hyperliquid']['use_testnet'] = env_str == 'testnet'

        # Copy trading settings
        if 'copy_trading' not in config:
            config['copy_trading'] = {}

        config['copy_trading']['copy_ratio'] = float(os.getenv('COPY_RATIO',
                                                             config['copy_trading'].get('copy_ratio', 0.1)))
        config['copy_trading']['max_position_size'] = float(os.getenv('MAX_POSITION_SIZE',
                                                                     config['copy_trading'].get('max_position_size', 1.0)))
        config['copy_trading']['min_trade_size'] = float(os.getenv('MIN_TRADE_SIZE',
                                                                  config['copy_trading'].get('min_trade_size', 0.01)))
        config['copy_trading']['max_leverage'] = int(os.getenv('MAX_LEVERAGE',
                                                              config['copy_trading'].get('max_leverage', 5)))

        # Risk management
        if 'risk_management' not in config:
            config['risk_management'] = {}

        config['risk_management']['max_drawdown'] = float(os.getenv('MAX_DRAWDOWN',
                                                                   config['risk_management'].get('max_drawdown', 0.1)))
        config['risk_management']['stop_loss_ratio'] = float(os.getenv('STOP_LOSS_RATIO',
                                                                      config['risk_management'].get('stop_loss_ratio', 0.05)))
        config['risk_management']['take_profit_ratio'] = float(os.getenv('TAKE_PROFIT_RATIO',
                                                                        config['risk_management'].get('take_profit_ratio', 0.1)))

        # Monitoring configuration
        if 'monitoring' not in config:
            config['monitoring'] = {}

        config['monitoring']['poll_interval'] = float(os.getenv('POLL_INTERVAL',
                                                             config['monitoring'].get('poll_interval', 30)))
        config['monitoring']['position_update_interval'] = int(os.getenv('POSITION_UPDATE_INTERVAL',
                                                                         config['monitoring'].get('position_update_interval', 10)))
        config['monitoring']['min_api_interval'] = int(os.getenv('MIN_API_INTERVAL',
                                                                 config['monitoring'].get('min_api_interval', 300)))
        config['monitoring']['max_retries'] = int(os.getenv('MAX_RETRIES',
                                                           config['monitoring'].get('max_retries', 3)))
        config['monitoring']['retry_delay'] = int(os.getenv('RETRY_DELAY',
                                                           config['monitoring'].get('retry_delay', 5)))

        # Telegram configuration
        if 'telegram' not in config:
            config['telegram'] = {}

        config['telegram']['enabled'] = os.getenv('TELEGRAM_ENABLED', 'true').lower() == 'true'
        config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN',
                                                   config['telegram'].get('bot_token', ''))
        config['telegram']['chat_id'] = os.getenv('TELEGRAM_CHAT_ID',
                                                 config['telegram'].get('chat_id', ''))

        # Fail-safe: if Telegram is enabled but missing credentials, auto-disable to avoid
        # hard failures on startup (users can re-enable once configured).
        if config['telegram'].get('enabled') and (not config['telegram'].get('bot_token') or not config['telegram'].get('chat_id')):
            config['telegram']['enabled'] = False
            logger.warning("⚠️ Telegram enabled but missing bot_token/chat_id; auto-disabled")

        # Logging configuration
        if 'logging' not in config:
            config['logging'] = {}

        config['logging']['level'] = os.getenv('LOG_LEVEL', config['logging'].get('level', 'INFO'))
        config['logging']['file'] = os.getenv('LOG_FILE', config['logging'].get('file', 'logs/copy_trader.log'))
        config['logging']['max_size'] = int(os.getenv('LOG_MAX_SIZE',
                                                     config['logging'].get('max_size', 10485760)))
        config['logging']['backup_count'] = int(os.getenv('LOG_BACKUP_COUNT',
                                                         config['logging'].get('backup_count', 5)))

        return config

    def _init_hyperliquid_clients(self):
        """初始化 Hyperliquid 客户端。"""
        hl_config = self.config.get('hyperliquid', {})
        use_testnet = hl_config.get('use_testnet', False)

        # 设置基础 URL
        base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL

        # 初始化信息客户端（仅用于REST查询；避免SDK默认启动WebSocket导致阻塞/资源占用）
        info_client = Info(base_url=base_url, skip_ws=True)

        # 初始化交易客户端
        account_address = hl_config.get('account_address', '')
        private_key = hl_config.get('private_key', '')

        if not account_address or not private_key:
            raise ValueError("Hyperliquid account_address and private_key are required")

        try:
            wallet = eth_account.Account.from_key(private_key)
            exchange_client = Exchange(
                wallet=wallet,
                base_url=base_url,
                account_address=account_address
            )

            # 初始化组件
            target_address = self.config.get('target_address', '')
            if not target_address:
                raise ValueError("target_address is required in config")

            # 获取排除地址列表
            exclude_addresses = self.config.get('exclude_addresses', [])
            if not isinstance(exclude_addresses, list):
                exclude_addresses = [exclude_addresses]

            # 传递监控配置到TradeMonitor
            monitoring_config = self.config.get('monitoring', {})

            # 根据配置选择监控方式
            if self.use_websocket:
                logger.info("🌐 Using WebSocket for real-time monitoring")
                # 初始化WebSocket监控器
                self.ws_monitor = WebSocketMonitor(
                    target_address,
                    use_testnet,
                    exclude_addresses,
                    on_trade_callback=self._handle_websocket_trade,
                    on_ready_callback=self._handle_ws_ready,
                )
                # 保留REST监控作为备份
                self.trade_monitor = TradeMonitor(
                    target_address,
                    use_testnet,
                    exclude_addresses,
                    min_api_interval=monitoring_config.get('min_api_interval', 5000)
                )
            else:
                logger.info("📡 Using REST polling for monitoring")
                self.trade_monitor = TradeMonitor(
                    target_address,
                    use_testnet,
                    exclude_addresses,
                    min_api_interval=monitoring_config.get('min_api_interval', 5000)
                )

            self.position_manager = PositionManager(exchange_client, info_client)

        except Exception as e:
            logger.error(f"Failed to initialize Hyperliquid clients: {e}")
            raise

    def _init_notifications(self):
        """初始化通知管理器。"""
        try:
            self.notification_manager = NotificationManager(self.config)
            logger.info("✅ Notification manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize notification manager: {e}")
            self.notification_manager = None

    async def start(self):
        """启动跟单交易器。"""
        if self.running:
            logger.warning("Copy trader is already running")
            return

        self.running = True
        logger.info("🚀 Starting Hyperliquid Copy Trader")

        # 初始化通知
        if self.notification_manager:
            await self.notification_manager.initialize()
            await self.notification_manager.notify_startup()
            await self._notify_startup_config_summary()

        # 设置信号处理
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, stopping...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # 根据配置选择监控方式
            if self.use_websocket:
                await self._websocket_monitoring_loop()
            else:
                await self._rest_monitoring_loop()

        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            # 停止WebSocket
            if self.ws_monitor:
                await self.ws_monitor.stop()

            # 发送关闭通知
            if self.notification_manager:
                await self.notification_manager.notify_shutdown()
                await self.notification_manager.close()

            logger.info("🛑 Hyperliquid Copy Trader stopped")

    async def _notify_startup_config_summary(self) -> None:
        """Send a one-shot startup self-check summary to Telegram.

        Intentionally excludes secrets (private keys, tokens).
        """
        try:
            nm = self.notification_manager
            tg = getattr(nm, 'telegram', None) if nm else None
            if tg is None:
                return

            copy_cfg = self.config.get('copy_trading', {})
            mon_cfg = self.config.get('monitoring', {})

            lines = [
                "🧾 *启动自检（配置摘要）*",
                "",
                f"目标地址: `{str(self.config.get('target_address', '') or '')}`",
                f"是否使用 WebSocket: `{str(self.use_websocket)}`",
                "",
                "*跟单设置*",
                f"跟单比例（COPY_RATIO）: `{copy_cfg.get('copy_ratio')}`",
                f"最大仓位（MAX_POSITION_SIZE）: `{copy_cfg.get('max_position_size')}`",
                f"最大杠杆（MAX_LEVERAGE）: `{copy_cfg.get('max_leverage')}`",
                "",
                "*稳定性/限流设置*",
                f"最小 API 间隔（ms）: `{mon_cfg.get('min_api_interval')}`",
                f"爆发批处理窗口（ms）: `{os.getenv('TRADE_BATCH_WINDOW_MS', '500')}`",
                "",
                "*断线恢复补单（Catch-up）*",
                f"是否启用: `{self._catchup_enabled}`",
                f"是否需要人工确认: `{self._catchup_require_approval}`",
                f"回看窗口（秒）: `{int(self._catchup_window_s)}`",
                f"最多补单数量: `{self._catchup_max_trades}`",
                f"重连后延迟（秒）: `{int(self._catchup_start_delay_s)}`",
                f"补单间隔（秒/笔）: `{float(self._catchup_replay_spacing_s):.1f}`",
            ]

            await tg.send_message("\n".join(lines))
        except Exception as e:
            logger.debug(f"Failed to send startup self-check: {e}")

    async def stop(self):
        """停止跟单交易器。"""
        self.running = False
        logger.info("Stopping Hyperliquid Copy Trader")

    async def _websocket_monitoring_loop(self):
        """WebSocket实时监控循环。"""
        logger.info("🌐 Starting WebSocket real-time monitoring...")
        logger.info("⚡ Real-time mode: <1s response time expected")

        try:
            # 启动WebSocket监控（异步任务）
            ws_task = asyncio.create_task(self.ws_monitor.start())

            monitoring_config = self.config.get('monitoring', {})
            # In WS mode, REST calls should be minimal to avoid API throttling.
            # We update positions frequently only around recent trades / when holding positions.
            status_log_interval_s = 60.0
            ws_stats_interval_s = 30.0
            batch_stats_interval_s = 60.0

            last_position_update = 0.0
            last_status_log = 0.0
            last_ws_stats = 0.0
            last_batch_stats = 0.0

            while self.running:
                await asyncio.sleep(1)

                # If websocket task dies, fallback to REST polling.
                if ws_task.done():
                    exc = ws_task.exception()
                    logger.error(f"WebSocket monitor stopped unexpectedly: {exc}")
                    self.use_websocket = False
                    return await self._rest_monitoring_loop()

                now = time.time()

                # Adaptive position refresh interval to balance speed vs API usage.
                # - If we currently hold positions: refresh a bit faster.
                # - If a trade was detected recently: refresh faster for quick close decisions.
                # - Otherwise back off to reduce API usage.
                has_positions = bool(getattr(self.position_manager, 'positions', {}))
                recent_trade = False
                if self.ws_monitor:
                    stats = self.ws_monitor.get_stats()
                    last_trade_time = stats.get('last_trade_time')
                    if last_trade_time:
                        try:
                            recent_trade = (now - last_trade_time.timestamp()) <= 15
                        except Exception:
                            recent_trade = False

                if recent_trade:
                    position_update_interval_s = 2.0
                elif has_positions:
                    position_update_interval_s = 5.0
                else:
                    position_update_interval_s = 15.0

                if (now - last_position_update) >= position_update_interval_s:
                    await self.position_manager.update_positions()
                    last_position_update = now

                if (now - last_status_log) >= status_log_interval_s:
                    await self._log_status()
                    last_status_log = now

                if (now - last_ws_stats) >= ws_stats_interval_s and self.ws_monitor:
                    stats = self.ws_monitor.get_stats()
                    logger.info(
                        f"📊 WebSocket Stats: {stats['trades_detected']} trades, "
                        f"{stats['streaming_messages']} msgs, snapshot={stats['snapshot_received']}"
                    )
                    last_ws_stats = now

                if (now - last_batch_stats) >= batch_stats_interval_s:
                    try:
                        b = self._trade_batcher.get_stats()
                        logger.info(
                            "📦 Batcher Stats: "
                            f"submitted={b.get('submitted')} batches={b.get('batches')} emitted={b.get('emitted')} "
                            f"last_batch={b.get('last_batch_size')} last_emit={b.get('last_emit_count')} dropped={b.get('dropped')}"
                        )
                    except Exception as e:
                        logger.debug(f"Failed to log batcher stats: {e}")
                    last_batch_stats = now

            # On normal exit, stop WS task.
            if not ws_task.done():
                ws_task.cancel()
                try:
                    await ws_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error in WebSocket monitoring loop: {e}")
            raise

    async def _rest_monitoring_loop(self):
        """REST轮询监控循环（备用方案）。"""
        copy_config = self.config.get('copy_trading', {})
        monitoring_config = self.config.get('monitoring', {})
        poll_interval = monitoring_config.get('poll_interval', 30)

        logger.info(f"📡 Starting REST polling monitoring with {poll_interval}s interval")

        consecutive_empty_checks = 0
        position_update_counter = 0
        position_update_interval = monitoring_config.get('position_update_interval', 10)  # 从配置读取仓位更新间隔

        batch_stats_interval_s = 60.0
        last_batch_stats = 0.0

        while self.running:
            start_time = time.time()

            try:
                # 优化：降低仓位更新频率，仅在需要时更新
                position_update_counter += 1
                if position_update_counter >= position_update_interval:
                    await self.position_manager.update_positions()
                    position_update_counter = 0

                # 检查新交易（保持高频）
                trades = await self.trade_monitor.get_recent_trades()

                # 处理每个新交易
                for trade in trades:
                    self._submit_trade(trade)

                # 记录状态（降低频率，仅在更新仓位时记录）
                if position_update_counter == 0:
                    await self._log_status()

                # 定时打印 batcher 指标，便于观察爆发合并效果
                now_s = time.time()
                if (now_s - last_batch_stats) >= batch_stats_interval_s:
                    try:
                        b = self._trade_batcher.get_stats()
                        logger.info(
                            "📦 Batcher Stats: "
                            f"submitted={b.get('submitted')} batches={b.get('batches')} emitted={b.get('emitted')} "
                            f"last_batch={b.get('last_batch_size')} last_emit={b.get('last_emit_count')} dropped={b.get('dropped')}"
                        )
                    except Exception as e:
                        logger.debug(f"Failed to log batcher stats: {e}")
                    last_batch_stats = now_s

                # 计算处理时间并调整等待时间
                processing_time = time.time() - start_time
                
                if trades:
                    consecutive_empty_checks = 0
                    logger.info(f"⚡ INSTANT: Processed {len(trades)} trades in {processing_time:.3f}s")
                    # 有交易时立即进行下一次检查
                    sleep_time = 0.05  # 50ms最小延迟
                else:
                    consecutive_empty_checks += 1
                    # 动态调整：连续空检查时逐渐增加间隔，最多到poll_interval
                    sleep_time = min(poll_interval, 0.1 + (consecutive_empty_checks * 0.05))
                
                # 等待下次检查
                await asyncio.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(poll_interval)

    async def _handle_websocket_trade(self, trade: MonitoredTrade):
        """处理WebSocket接收到的交易（回调函数）。"""
        self._submit_trade(trade)

    async def _handle_ws_ready(self):
        """Called when WS receives snapshot (connection is ready).

        If enabled, we do a bounded REST catch-up for missed fills, but only
        replay those with strictly better current prices.
        """
        if not self._catchup_enabled:
            return
        if not self.running:
            return
        if not self.use_websocket:
            return

        if self._catchup_task and not self._catchup_task.done():
            return

        async def _runner():
            # Optional delay: if you don't want immediate REST calls on reconnect,
            # wait a bit and let the system stabilize.
            if self._catchup_start_delay_s > 0:
                await asyncio.sleep(self._catchup_start_delay_s)

            now = time.monotonic()
            if (now - self._last_catchup_at) < self._catchup_min_interval_s:
                return
            self._last_catchup_at = now

            try:
                await self._catch_up_missed_trades_strict_better()
            except Exception as e:
                logger.warning(f"Catch-up skipped due to error: {e}")

        self._catchup_task = asyncio.create_task(_runner())

    async def _catch_up_missed_trades_strict_better(self):
        if not self.position_manager or not self.ws_monitor:
            return

        target = self.config.get('target_address', '')
        if not target:
            return

        # If the network was down for hours, we do NOT try to backfill everything.
        # Only consider a recent bounded window.
        now_ms = int(time.time() * 1000)
        window_ms = int(max(0.0, self._catchup_window_s) * 1000)
        since_ms = max(int(getattr(self.ws_monitor, 'last_check_timestamp', 0) or 0), now_ms - window_ms)

        # Fetch current mids once (1 REST call)
        mids = await asyncio.to_thread(self.position_manager.info.all_mids)
        if not isinstance(mids, dict) or not mids:
            return

        # Fetch fills once (1 REST call)
        fills = await asyncio.to_thread(self.position_manager.info.user_fills, target)
        if not fills:
            return

        processed = getattr(self.ws_monitor, 'processed_tx_hashes', set())
        exclude = set(getattr(self.ws_monitor, 'exclude_addresses', []) or [])

        # Oldest -> newest
        fills_sorted = sorted(fills, key=lambda f: int(f.get('time', 0) or 0))

        replayed = 0
        considered = 0
        eligible_trades: list[MonitoredTrade] = []
        eligible_hashes: list[str] = []

        for fill in fills_sorted:
            if replayed >= self._catchup_max_trades:
                break

            try:
                ts = int(fill.get('time', 0) or 0)
                if ts < since_ms:
                    continue

                txh = str(fill.get('hash', '') or '')
                if not txh or txh in processed:
                    continue

                user = str(fill.get('user', '') or '').lower()
                if user and user in exclude:
                    processed.add(txh)
                    continue

                coin = str(fill.get('coin', '') or '')
                side = str(fill.get('side', '') or '')
                fill_px = float(fill.get('px', 0) or 0)
                sz = float(fill.get('sz', 0) or 0)
                if not coin or side not in ('B', 'A') or fill_px <= 0 or sz <= 0:
                    processed.add(txh)
                    continue

                mid_raw = mids.get(coin)
                if mid_raw is None:
                    processed.add(txh)
                    continue
                mid = float(mid_raw)

                # Strictly better only:
                # - If we need to BUY, current mid must be strictly lower.
                # - If we need to SELL, current mid must be strictly higher.
                better = (mid < fill_px) if side == 'B' else (mid > fill_px)
                considered += 1
                if not better:
                    processed.add(txh)
                    continue

                # Build MonitoredTrade (keep semantics aligned with existing logic)
                from .trade_monitor import TradeAction
                action = TradeAction.OPEN_LONG if side == 'B' else TradeAction.OPEN_SHORT
                leverage = int(fill.get('leverage', 1) or 1)
                trade = MonitoredTrade(
                    action=action,
                    coin=coin,
                    size=sz,
                    price=fill_px,
                    leverage=leverage,
                    timestamp=ts,
                    tx_hash=txh,
                    side=side,
                )

                eligible_trades.append(trade)
                eligible_hashes.append(txh)
                replayed += 1

            except Exception:
                # Defensive: never let one bad fill break reconnect.
                continue

        if replayed <= 0:
            if considered > 0:
                logger.info(
                    f"🔁 Catch-up (strict better): considered={considered}, eligible=0, window={int(self._catchup_window_s)}s"
                )
            return

        logger.info(
            f"🔁 Catch-up (strict better): considered={considered}, eligible={replayed}, window={int(self._catchup_window_s)}s"
        )

        # Approval flow
        if self._catchup_require_approval:
            eligible_trades = await self._two_step_catchup_approval(eligible_trades)

        if not eligible_trades:
            # Mark these hashes as processed to avoid repeated prompts on every reconnect.
            for h in eligible_hashes:
                processed.add(h)
            logger.info("🔕 Catch-up skipped by operator or no longer better")
            return

        # Replay slowly to avoid bursts
        await self._replay_catchup_trades_slowly(eligible_trades)

        # After replay is scheduled/submitted, mark processed and advance timestamp.
        max_ts = getattr(self.ws_monitor, 'last_check_timestamp', 0)
        for t in eligible_trades:
            processed.add(t.tx_hash)
            if int(t.timestamp) > int(max_ts):
                max_ts = int(t.timestamp)
        self.ws_monitor.last_check_timestamp = int(max_ts)

    async def _replay_catchup_trades_slowly(self, trades: list[MonitoredTrade]) -> None:
        if not trades:
            return

        spacing = max(0.0, float(self._catchup_replay_spacing_s))
        for idx, t in enumerate(trades, start=1):
            if not self.running:
                return
            # Still submit into batcher (keeps rate limits + nets per coin if needed)
            self._submit_trade(t)
            if spacing > 0 and idx != len(trades):
                await asyncio.sleep(spacing)

    async def _two_step_catchup_approval(self, trades: list[MonitoredTrade]) -> list[MonitoredTrade]:
        """Two-step Telegram approval with a price re-check.

        Step 1: operator replies YES/NO.
        Step 2 (if YES): re-check current mids and keep only trades that are still strictly better,
                then require CONFIRM/NO.
        """
        nm = self.notification_manager
        tg = getattr(nm, 'telegram', None) if nm else None
        if tg is None:
            logger.warning("Catch-up approval required but Telegram is not configured; skipping catch-up")
            return []

        token1 = secrets.token_hex(3).upper()
        msg1 = (
            "🔁 *Catch-up pending* (strict better only)\n\n"
            f"Eligible trades (pre-check): *{len(trades)}*\n"
            f"Replay spacing: *{float(self._catchup_replay_spacing_s):.1f}s* per trade\n\n"
            f"Reply: `YES {token1}` to continue, or `NO {token1}` to skip.\n"
            f"Timeout: {int(self._catchup_approval_timeout_s)}s"
        )
        await tg.send_message(msg1)

        decision1 = await self._await_telegram_token_reply(
            token=token1,
            timeout_s=float(self._catchup_approval_timeout_s),
            accept_prefixes=("YES", "NO"),
        )
        if decision1 != "YES":
            return []

        # Re-check target current positions (if the target already closed, no need to backfill).
        relevant = await self._filter_trades_target_still_open(trades)
        if not relevant:
            await tg.send_message("ℹ️ Re-check result: target has already closed (or is flat). Skipping catch-up.")
            return []

        # Re-check current mids and re-filter strictly better *now*.
        filtered = await self._filter_trades_strict_better_now(relevant)
        if not filtered:
            await tg.send_message("ℹ️ Re-check result: 0 trades are still strictly better. Skipping catch-up.")
            return []

        token2 = secrets.token_hex(3).upper()
        msg2 = (
            "✅ *Re-check complete* (strict better now)\n\n"
            f"Still eligible: *{len(filtered)}* / {len(trades)}\n"
            f"Replay spacing: *{float(self._catchup_replay_spacing_s):.1f}s* per trade\n\n"
            f"Reply: `CONFIRM {token2}` to replay, or `NO {token2}` to cancel.\n"
            f"Timeout: {int(self._catchup_second_confirm_timeout_s)}s"
        )
        await tg.send_message(msg2)

        decision2 = await self._await_telegram_token_reply(
            token=token2,
            timeout_s=float(self._catchup_second_confirm_timeout_s),
            accept_prefixes=("CONFIRM", "NO"),
        )
        if decision2 != "CONFIRM":
            return []

        await tg.send_message(f"✅ Catch-up confirmed: `{len(filtered)}` trades will replay slowly")
        return filtered

    async def _filter_trades_strict_better_now(self, trades: list[MonitoredTrade]) -> list[MonitoredTrade]:
        if not trades or not self.position_manager:
            return []

        mids = await asyncio.to_thread(self.position_manager.info.all_mids)
        if not isinstance(mids, dict) or not mids:
            return []

        out: list[MonitoredTrade] = []
        for t in trades:
            try:
                mid_raw = mids.get(t.coin)
                if mid_raw is None:
                    continue
                mid = float(mid_raw)
                px = float(getattr(t, 'price', 0) or 0)
                side = getattr(t, 'side', None)
                if side not in ("B", "A") or px <= 0:
                    continue
                better = (mid < px) if side == "B" else (mid > px)
                if better:
                    out.append(t)
            except Exception:
                continue
        return out

    async def _filter_trades_target_still_open(self, trades: list[MonitoredTrade]) -> list[MonitoredTrade]:
        """Filter catch-up trades by the target's current positions.

        If the target has already flattened/closed a coin, we don't want to
        replay historical fills that would re-open our position.
        """
        if not trades or not self.position_manager:
            return []

        target = self.config.get('target_address', '')
        if not target:
            return []

        try:
            state = await asyncio.to_thread(self.position_manager.info.user_state, target)
        except Exception as e:
            # Conservative: if we can't verify target is still in-position, skip catch-up.
            logger.warning(f"Target position re-check failed; skipping catch-up: {e}")
            return []

        positions: dict[str, float] = {}
        try:
            for pos_data in (state or {}).get('assetPositions', []) or []:
                p = pos_data.get('position', {}) or {}
                coin = p.get('coin') or pos_data.get('coin')
                if not coin:
                    continue
                szi = float(p.get('szi', 0) or 0)
                if szi == 0:
                    continue
                positions[str(coin)] = szi
        except Exception:
            positions = {}

        out: list[MonitoredTrade] = []
        for t in trades:
            try:
                szi = float(positions.get(t.coin, 0.0))
                if szi == 0:
                    continue

                side = getattr(t, 'side', None)
                if side == 'B' and szi > 0:
                    out.append(t)
                elif side == 'A' and szi < 0:
                    out.append(t)
            except Exception:
                continue

        return out

    async def _await_telegram_token_reply(self, *, token: str, timeout_s: float, accept_prefixes: tuple[str, ...]) -> Optional[str]:
        """Wait for a Telegram reply containing the token.

        Returns the matched prefix (upper-case) or None on timeout.
        """
        nm = self.notification_manager
        tg = getattr(nm, 'telegram', None) if nm else None
        if tg is None:
            return None

        # Drain old updates the first time we ever poll, so we don't match stale messages.
        if self._tg_update_offset is None:
            updates = await tg.get_updates(offset=None, timeout_s=0)
            if updates:
                try:
                    last_id = max(int(u.get('update_id', 0) or 0) for u in updates)
                    self._tg_update_offset = last_id + 1
                except Exception:
                    self._tg_update_offset = None

        deadline = time.monotonic() + max(1.0, float(timeout_s))
        expected_chat_id = str(self.config.get('telegram', {}).get('chat_id', '') or '')

        while time.monotonic() < deadline and self.running:
            remaining = deadline - time.monotonic()
            timeout = int(max(0, min(30, remaining)))
            updates = await tg.get_updates(offset=self._tg_update_offset, timeout_s=timeout)

            if updates:
                try:
                    max_update_id = max(int(u.get('update_id', 0) or 0) for u in updates)
                    self._tg_update_offset = max_update_id + 1
                except Exception:
                    pass

            for u in updates:
                m = u.get('message') or {}
                chat = m.get('chat') or {}
                chat_id = str(chat.get('id', '') or '')
                text = str(m.get('text', '') or '').strip()
                if not text:
                    continue
                if expected_chat_id and chat_id != expected_chat_id:
                    continue

                upper = text.upper()
                if token not in upper:
                    continue

                for pref in accept_prefixes:
                    if upper.startswith(pref):
                        return pref

            await asyncio.sleep(max(0.2, float(self._catchup_approval_poll_s)))

        try:
            await tg.send_message(f"⏱️ Catch-up prompt timed out (no reply): skipping `... {token}`")
        except Exception:
            pass
        return None

    def _submit_trade(self, trade: MonitoredTrade):
        """Submit a trade into the burst batcher."""
        self._trade_batcher.submit(trade)

    async def _handle_trade_batch(self, trades: list[MonitoredTrade]):
        """Handle a batch of aggregated trades (per-coin netted)."""
        copy_config = self.config.get('copy_trading', {})
        # One positions refresh per batch (debounced + rate-limited internally)
        if self.position_manager:
            await self.position_manager.update_positions()

        for trade in trades:
            await self._handle_new_trade(trade, copy_config)

    async def _handle_new_trade(self, trade: MonitoredTrade, copy_config: Dict[str, Any]):
        """处理新监控到的交易。"""
        start_time = time.time()

        try:
            logger.info(f"⚡ Processing new trade: {trade}")

            # 检查是否启用跟单
            if not copy_config.get('enabled', True):
                logger.debug("Copy trading is disabled")
                return

            # 获取跟单参数
            copy_ratio = copy_config.get('copy_ratio', 0.1)
            max_size = copy_config.get('max_position_size', 1.0)
            max_leverage = copy_config.get('max_leverage', 5)

            # 执行跟单
            await self.position_manager.execute_copy_trade(trade, copy_ratio, max_size, max_leverage=max_leverage)

            # 计算响应时间
            response_time = time.time() - start_time
            logger.info(f"✅ Trade executed in {response_time:.3f}s")

            # 发送交易通知
            if self.notification_manager:
                trade_data = {
                    'action': trade.action,
                    'coin': trade.coin,
                    'size': trade.size * copy_ratio,  # 实际跟单大小
                    'price': trade.price,
                    'leverage': trade.leverage,
                    'response_time': f"{response_time:.3f}s"
                }
                await self.notification_manager.notify_trade(trade_data)

        except Exception as e:
            logger.error(f"Error handling trade {trade}: {e}")

            # 发送错误通知
            if self.notification_manager:
                await self.notification_manager.notify_alert(
                    "error",
                    f"处理交易失败: {trade.coin} {trade.action}\n错误: {str(e)}"
                )

    async def _log_status(self):
        """记录当前状态。"""
        try:
            if not self.position_manager:
                return

            summary = self.position_manager.get_positions_summary()
            total_pnl = summary.get('total_pnl', 0.0)
            total_positions = int(summary.get('total_positions', 0) or 0)

            logger.info(
                f"Status: {total_positions} positions, "
                f"Total PnL: ${float(total_pnl):.2f}"
            )

            # 发送状态通知（有仓位才发；并且限频，避免频繁打扰）
            current_time = time.time()
            if self.notification_manager:
                if self._status_notify_only_when_positions and total_positions <= 0:
                    # 没仓位不推送；并重置计时器，方便下次有仓位时尽快发一次状态。
                    self._last_status_notification = 0.0
                elif (current_time - self._last_status_notification) >= self._status_notification_interval:
                    await self.notification_manager.notify_status(summary)
                    self._last_status_notification = current_time

            # 检查风险控制
            await self._check_risk_limits(float(total_pnl))

        except Exception as e:
            logger.error(f"Error logging status: {e}")

    async def _check_risk_limits(self, current_pnl: float):
        """检查风险限制。"""
        risk_config = self.config.get('risk_management', {})

        # 检查最大回撤
        max_drawdown = float(risk_config.get('max_drawdown', 0.1))
        if current_pnl < -max_drawdown:
            logger.warning(f"Max drawdown exceeded: {current_pnl} < -{max_drawdown}")

            if self.notification_manager:
                await self.notification_manager.notify_alert(
                    "warning",
                    f"⚠️ 最大回撤超限!\n当前亏损: ${current_pnl:.2f}\n回撤限制: ${max_drawdown:.2f}",
                )

        # 检查止损
        stop_loss_ratio = float(risk_config.get('stop_loss_ratio', 0.05))
        if current_pnl < -stop_loss_ratio:
            logger.warning(f"Stop loss triggered: {current_pnl} < -{stop_loss_ratio}")

            if self.notification_manager:
                await self.notification_manager.notify_alert(
                    "error",
                    f"🚨 止损触发!\n当前亏损: ${current_pnl:.2f}\n止损线: ${stop_loss_ratio:.2f}\n建议立即检查!",
                )