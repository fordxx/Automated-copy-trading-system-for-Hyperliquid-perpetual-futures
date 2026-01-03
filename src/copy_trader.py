"""Main Copy Trader implementation for Hyperliquid.

整合交易监控和仓位管理，实现自动跟单功能。
"""
import asyncio
from collections import deque
import logging
import signal
import sys
import time
from typing import Dict, Any, Optional
import yaml
import os
from pathlib import Path
from dotenv import load_dotenv
import secrets

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .trade_monitor import TradeMonitor, MonitoredTrade, TradeAction
from .websocket_monitor import WebSocketMonitor
from .position_manager import PositionManager
from .notifications import NotificationManager
from .trade_batcher import TradeBatcher

logger = logging.getLogger(__name__)


def _safe_get_env_float(key: str, default: float, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
    """Safely get and validate a float environment variable."""
    try:
        value = float(os.getenv(key, str(default)))
        if min_val is not None and value < min_val:
            logger.warning(f"Env {key}={value} below minimum {min_val}, using minimum")
            return min_val
        if max_val is not None and value > max_val:
            logger.warning(f"Env {key}={value} above maximum {max_val}, using maximum")
            return max_val
        return value
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid env {key}={os.getenv(key)}, using default {default}: {e}")
        return default


def _safe_get_env_int(key: str, default: int, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """Safely get and validate an int environment variable."""
    try:
        value = int(os.getenv(key, str(default)))
        if min_val is not None and value < min_val:
            logger.warning(f"Env {key}={value} below minimum {min_val}, using minimum")
            return min_val
        if max_val is not None and value > max_val:
            logger.warning(f"Env {key}={value} above maximum {max_val}, using maximum")
            return max_val
        return value
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid env {key}={os.getenv(key)}, using default {default}: {e}")
        return default


class HyperliquidCopyTrader:
    """Hyperliquid 自动跟单交易器。

    监控指定地址的交易并自动复制到自己的账户。
    """

    def __init__(self, config_path: Optional[str] = None, config_dict: Optional[Dict[str, Any]] = None):
        # Load environment variables.
        # Use an explicit path so detached/background runs don't miss the repo-root .env.
        try:
            repo_root = Path(__file__).resolve().parent.parent
            load_dotenv(dotenv_path=repo_root / '.env', override=False)
        except Exception:
            load_dotenv()

        self.config = self._load_config(config_path, config_dict)
        self.running = False

        # 获取钱包标识（用于电报通知中区分不同实例）
        self.wallet_label = os.getenv('INSTANCE_NAME', '').strip()
        if not self.wallet_label:
            # 单实例运行时，如果没有 INSTANCE_NAME，使用地址作为标识
            self.wallet_label = self.config.get('hyperliquid', {}).get('account_address', '')[:10] + '...' if self.config.get('hyperliquid', {}).get('account_address') else ''
        self.account_address = self.config.get('hyperliquid', {}).get('account_address', '')

        # 初始化组件
        self.trade_monitor: Optional[TradeMonitor] = None
        self.ws_monitor: Optional[WebSocketMonitor] = None
        self.position_manager: Optional[PositionManager] = None
        self.notification_manager: Optional[NotificationManager] = None

        # Centralized trade deduplication (shared between REST and WS monitors)
        self._processed_tx_hashes: set[str] = set()
        self._processed_tx_order: deque[str] = deque()
        self._inflight_tx_hashes: set[str] = set()
        self._dedup_lock = asyncio.Lock()
        self._max_dedup_set_size = _safe_get_env_int('MAX_DEDUP_SET_SIZE', 10000, min_val=100, max_val=100000)

        # WebSocket模式标志
        self.use_websocket = os.getenv('USE_WEBSOCKET', 'true').lower() == 'true'

        # Burst batching: reduces 429s and order spam when the target opens/closes many trades.
        batch_window_ms = _safe_get_env_float('TRADE_BATCH_WINDOW_MS', 500.0, min_val=0.0, max_val=10000.0)
        self._trade_batcher = TradeBatcher(window_s=batch_window_ms / 1000.0, on_batch=self._handle_trade_batch)

        # Reconnect catch-up (optional): after WS reconnect, backfill a bounded window via REST,
        # but only if the current price is strictly better than the original fill.
        self._catchup_enabled = os.getenv('CATCHUP_ENABLED', 'true').lower() == 'true'
        # Safety: default OFF. Replaying OPEN fills on reconnect/startup can double exposure.
        # Keep CLOSE replays for correctness, but treat OPEN replays as opt-in.
        self._catchup_replay_opens = os.getenv('CATCHUP_REPLAY_OPENS', 'false').lower() == 'true'
        self._catchup_window_s = _safe_get_env_float('CATCHUP_WINDOW_S', 600.0, min_val=0.0, max_val=86400.0)
        self._catchup_max_trades = _safe_get_env_int('CATCHUP_MAX_TRADES', 200, min_val=1, max_val=10000)
        self._catchup_min_interval_s = _safe_get_env_float('CATCHUP_MIN_INTERVAL_S', 30.0, min_val=0.0)
        self._catchup_start_delay_s = _safe_get_env_float('CATCHUP_START_DELAY_S', 0.0, min_val=0.0, max_val=3600.0)
        self._last_catchup_at = 0.0
        self._catchup_task: Optional[asyncio.Task] = None

        # Operator-in-the-loop approval (Telegram): ask before replaying catch-up trades.
        self._catchup_require_approval = os.getenv('CATCHUP_REQUIRE_APPROVAL', 'false').lower() == 'true'
        self._catchup_approval_timeout_s = _safe_get_env_float('CATCHUP_APPROVAL_TIMEOUT_S', 900.0, min_val=10.0, max_val=7200.0)
        default_second_timeout = self._catchup_approval_timeout_s
        self._catchup_second_confirm_timeout_s = _safe_get_env_float('CATCHUP_SECOND_CONFIRM_TIMEOUT_S', default_second_timeout, min_val=10.0, max_val=7200.0)
        self._catchup_approval_poll_s = _safe_get_env_float('CATCHUP_APPROVAL_POLL_S', 2.0, min_val=0.2, max_val=60.0)
        self._catchup_replay_spacing_s = _safe_get_env_float('CATCHUP_REPLAY_SPACING_S', 2.0, min_val=0.0, max_val=60.0)
        self._tg_update_offset: Optional[int] = None

        # Periodic position ratio sync (corrective "snap-to" with price gating).
        # Disabled by default for safety; enable via env:
        #   POSITION_SYNC_ENABLED=true
        self._position_sync_enabled = os.getenv('POSITION_SYNC_ENABLED', 'false').lower() == 'true'
        self._position_sync_interval_s = _safe_get_env_float('POSITION_SYNC_INTERVAL_S', 300.0, min_val=30.0, max_val=86400.0)
        self._position_sync_start_delay_s = _safe_get_env_float('POSITION_SYNC_START_DELAY_S', 30.0, min_val=0.0, max_val=3600.0)
        self._position_sync_min_rel_diff = _safe_get_env_float('POSITION_SYNC_MIN_REL_DIFF', 0.05, min_val=0.0, max_val=1.0)
        # Price gate: only execute sync orders when mid is not worse than reference entry by this pct.
        # 0.0 means "strict better-or-equal".
        self._position_sync_allow_worse_pct = _safe_get_env_float('POSITION_SYNC_ALLOW_WORSE_PCT', 0.0, min_val=0.0, max_val=0.5)
        # Stricter gate: compare current mid vs leader's latest OPEN fill price for the same side.
        # Values: "strict_fill_open" (strictly better) | "entry" (entryPx-based, allows allow_worse_pct)
        self._position_sync_price_ref_mode = os.getenv('POSITION_SYNC_PRICE_REF_MODE', 'strict_fill_open').strip().lower()
        # If strict fill ref is missing, either "skip" (default) or fall back to "entry".
        self._position_sync_fill_ref_fallback = os.getenv('POSITION_SYNC_FILL_REF_FALLBACK', 'skip').strip().lower()
        # Optional spread gate (default OFF): avoid syncing in wide markets.
        self._position_sync_spread_gate_enabled = os.getenv('POSITION_SYNC_SPREAD_GATE_ENABLED', 'false').lower() == 'true'
        self._position_sync_max_spread_bps = _safe_get_env_float('POSITION_SYNC_MAX_SPREAD_BPS', 0.0, min_val=0.0, max_val=1000.0)
        # By default we always allow reductions (risk-off) even if price is "not ideal".
        self._position_sync_gate_reductions = os.getenv('POSITION_SYNC_GATE_REDUCTIONS', 'false').lower() == 'true'
        self._position_sync_min_notional_usd = _safe_get_env_float('POSITION_SYNC_MIN_NOTIONAL_USD', 10.0, min_val=0.0)
        self._position_sync_default_leverage = _safe_get_env_int('POSITION_SYNC_DEFAULT_LEVERAGE', 5, min_val=1, max_val=50)
        self._position_sync_task: Optional[asyncio.Task] = None
        self._position_sync_lock = asyncio.Lock()
        # Track leader-trade recency per coin to avoid sync fighting real-time execution.
        self._last_leader_trade_at_by_coin: dict[str, float] = {}
        self._position_sync_skip_recent_trade_s = _safe_get_env_float('POSITION_SYNC_SKIP_RECENT_TRADE_S', 30.0, min_val=0.0, max_val=3600.0)

        # 初始化 Hyperliquid 客户端
        self._init_hyperliquid_clients()

        # 初始化通知管理器
        self._init_notifications()

        # 状态通知限制（避免频繁发送Telegram消息）
        # 需求：有开/平仓会走交易通知；状态推送仅在“有仓位”时周期发送。
        self._last_status_notification = 0.0
        self._status_notify_only_when_positions = os.getenv('STATUS_NOTIFY_ONLY_WHEN_POSITIONS', 'true').lower() == 'true'
        self._status_notification_interval = float(os.getenv('STATUS_NOTIFICATION_INTERVAL_S', '1800'))  # 默认 30 分钟

        # Risk alert throttling (avoid spamming Telegram on every status tick).
        self._risk_alert_min_interval_s = float(os.getenv('RISK_ALERT_MIN_INTERVAL_S', '300'))
        self._last_risk_alert_at: dict[str, float] = {}

        # Optional: auto-flatten on stop-loss.
        # NOTE: default is disabled (alerts only). Enable via env:
        #   RISK_AUTO_CLOSE_ON_STOP_LOSS=true
        self._risk_auto_close_on_stop_loss = os.getenv('RISK_AUTO_CLOSE_ON_STOP_LOSS', 'false').lower() == 'true'
        self._risk_auto_close_cooldown_s = float(os.getenv('RISK_AUTO_CLOSE_COOLDOWN_S', '300'))
        self._risk_auto_close_and_stop = os.getenv('RISK_AUTO_CLOSE_AND_STOP', 'false').lower() == 'true'
        self._risk_halt_trading_on_stop_loss = os.getenv('RISK_HALT_TRADING_ON_STOP_LOSS', 'true').lower() == 'true'
        self._stop_loss_exec_in_progress = False
        self._last_stop_loss_exec_at = 0.0
        self._trading_halted = False
        self._trading_halted_reason: Optional[str] = None
        self._last_halt_log_at = 0.0

        # Optional: auto-close positions on stop-loss trigger (default OFF for safety).
        self._auto_close_on_stop_loss = os.getenv('RISK_AUTO_CLOSE_ON_STOP_LOSS', 'false').lower() == 'true'
        self._risk_close_lock = asyncio.Lock()

        if self._risk_auto_close_on_stop_loss:
            logger.warning(
                "🧯 Stop-loss auto-close is ENABLED (cooldown=%ss halt=%s stop=%s)",
                int(self._risk_auto_close_cooldown_s),
                self._risk_halt_trading_on_stop_loss,
                self._risk_auto_close_and_stop,
            )
        logger.info("✅ HyperliquidCopyTrader initialized")

    def _load_config(self, config_path: Optional[str] = None, config_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """加载配置文件，支持环境变量覆盖。"""
        config = {}

        # 优先使用直接传入的配置字典（用于多实例模式）
        if config_dict:
            config = config_dict.copy()
            logger.info("Loaded config from provided dictionary")
        # 如果提供了配置文件路径，先加载YAML配置
        elif config_path and os.path.exists(config_path):
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

        # Copy mode: "position" (根据仓位大小比例) 或 "wallet" (根据钱包余额比例)
        config['copy_trading']['copy_mode'] = os.getenv('COPY_MODE',
                                                       config['copy_trading'].get('copy_mode', 'position')).lower()
        config['copy_trading']['copy_ratio'] = float(os.getenv('COPY_RATIO',
                                                             config['copy_trading'].get('copy_ratio', 0.1)))
        config['copy_trading']['max_position_size'] = float(os.getenv('MAX_POSITION_SIZE',
                                                                     config['copy_trading'].get('max_position_size', 1.0)))
        # Optional: cap per-trade notional in USD (e.g. 2000 means ~$2000 max per order).
        # When set > 0, this is applied in addition to COPY_RATIO.
        config['copy_trading']['max_notional_per_trade_usd'] = float(
            os.getenv(
                'MAX_NOTIONAL_PER_TRADE_USD',
                config['copy_trading'].get('max_notional_per_trade_usd', 0.0),
            )
        )
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
            # Pass instance labels so notifications can identify which wallet/instance
            self.notification_manager = NotificationManager(self.config, wallet_label=self.wallet_label, account_address=self.account_address)
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

        if self._risk_auto_close_on_stop_loss:
            logger.warning(
                "🧯 Stop-loss auto-close ENABLED: cooldown=%ss halt=%s stop=%s",
                int(self._risk_auto_close_cooldown_s),
                self._risk_halt_trading_on_stop_loss,
                self._risk_auto_close_and_stop,
            )

        # 初始化 PositionManager（预热 szDecimals 缓存）
        if self.position_manager:
            await self.position_manager.initialize()

        # 初始化通知
        if self.notification_manager:
            await self.notification_manager.initialize()
            await self.notification_manager.notify_startup()
            await self._notify_startup_config_summary()

        # Start periodic position sync (independent of WS/REST monitoring loops).
        if self._position_sync_enabled and self.position_manager:
            logger.warning(
                "🧭 Position sync ENABLED: interval=%ss price_mode=%s fallback=%s spread_gate=%s max_spread_bps=%s allow_worse_pct=%s gate_reductions=%s",
                int(self._position_sync_interval_s),
                str(self._position_sync_price_ref_mode),
                str(self._position_sync_fill_ref_fallback),
                bool(self._position_sync_spread_gate_enabled),
                float(self._position_sync_max_spread_bps),
                float(self._position_sync_allow_worse_pct),
                bool(self._position_sync_gate_reductions),
            )
            self._position_sync_task = asyncio.create_task(self._position_sync_loop())

        # 设置信号处理
        # Background runs (setsid/nohup with stdin=/dev/null) should not be stoppable
        # by stray SIGINT (signal 2). We still stop on SIGTERM for service management.
        ignore_sigint_when_detached = os.getenv('IGNORE_SIGINT_WHEN_DETACHED', 'true').lower() == 'true'
        is_detached = not sys.stdin.isatty()
        _last_sigint_log_at = 0.0

        def signal_handler(signum, frame):
            nonlocal _last_sigint_log_at

            if signum == signal.SIGINT and ignore_sigint_when_detached and is_detached:
                now = time.time()
                # Throttle logs in case something is spamming SIGINT.
                if now - _last_sigint_log_at >= 60:
                    logger.warning("Ignoring SIGINT (signal 2) because process is detached")
                    _last_sigint_log_at = now
                return

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

            # Stop background sync loop.
            if self._position_sync_task and not self._position_sync_task.done():
                self._position_sync_task.cancel()
                try:
                    await self._position_sync_task
                except Exception:
                    pass

            # 发送关闭通知
            if self.notification_manager:
                await self.notification_manager.notify_shutdown()
                await self.notification_manager.close()

            logger.info("🛑 Hyperliquid Copy Trader stopped")

    async def _is_trade_processed(self, tx_hash: str) -> bool:
        """Check if a trade has already been processed (thread-safe)."""
        async with self._dedup_lock:
            return tx_hash in self._processed_tx_hashes or tx_hash in self._inflight_tx_hashes

    async def _mark_trade_processed(self, tx_hash: str) -> None:
        """Mark a trade as processed, with bounded set size (thread-safe)."""
        async with self._dedup_lock:
            if tx_hash in self._processed_tx_hashes:
                return
            self._processed_tx_hashes.add(tx_hash)
            self._processed_tx_order.append(tx_hash)
            # Prune oldest entries if set grows too large (true FIFO).
            while len(self._processed_tx_order) > self._max_dedup_set_size:
                old = self._processed_tx_order.popleft()
                self._processed_tx_hashes.discard(old)
            if tx_hash in self._inflight_tx_hashes:
                self._inflight_tx_hashes.discard(tx_hash)

    async def _mark_trade_inflight(self, tx_hash: str) -> None:
        """Track a trade while it is being processed to avoid duplicate work."""
        async with self._dedup_lock:
            self._inflight_tx_hashes.add(tx_hash)

    async def _clear_trade_inflight(self, tx_hash: str) -> None:
        async with self._dedup_lock:
            self._inflight_tx_hashes.discard(tx_hash)

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
                f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}",
                f"目标地址: `{str(self.config.get('target_address', '') or '')}`",
                f"跟随地址: `{str(self.config.get('hyperliquid', {}).get('account_address', '') or '')}`",
                f"是否使用 WebSocket: `{str(self.use_websocket)}`",
                "",
                "*跟单设置*",
                f"跟单比例（COPY_RATIO）: `{copy_cfg.get('copy_ratio')}`",
                f"最大仓位（MAX_POSITION_SIZE）: `{copy_cfg.get('max_position_size')}`",
                f"单笔名义上限（MAX_NOTIONAL_PER_TRADE_USD）: `{copy_cfg.get('max_notional_per_trade_usd')}`",
                f"最大杠杆（MAX_LEVERAGE）: `{copy_cfg.get('max_leverage')}`",
                "",
                "*稳定性/限流设置*",
                f"最小 API 间隔（ms）: `{mon_cfg.get('min_api_interval')}`",
                f"爆发批处理窗口（ms）: `{os.getenv('TRADE_BATCH_WINDOW_MS', '500')}`",
                "",
                "*断线恢复补单（Catch-up）*",
                f"是否启用: `{self._catchup_enabled}`",
                f"是否回放 OPEN: `{self._catchup_replay_opens}`",
                f"是否需要人工确认: `{self._catchup_require_approval}`",
                f"回看窗口（秒）: `{int(self._catchup_window_s)}`",
                f"最多补单数量: `{self._catchup_max_trades}`",
                f"重连后延迟（秒）: `{int(self._catchup_start_delay_s)}`",
                f"补单间隔（秒/笔）: `{float(self._catchup_replay_spacing_s):.1f}`",
                "",
                "*仓位纠偏（Position Sync）*",
                f"是否启用: `{self._position_sync_enabled}`",
                f"检查间隔（秒）: `{int(self._position_sync_interval_s)}`",
                f"价格参考模式: `{str(self._position_sync_price_ref_mode)}`",
                f"严格模式缺失参考价回退: `{str(self._position_sync_fill_ref_fallback)}`",
                f"点差门控: `{bool(self._position_sync_spread_gate_enabled)}` / max_bps=`{float(self._position_sync_max_spread_bps)}`",
                f"价格容忍（pct）: `{float(self._position_sync_allow_worse_pct)}`",
                f"是否也对减仓做价格门控: `{bool(self._position_sync_gate_reductions)}`",
            ]

            await tg.send_message("\n".join(lines))
        except Exception as e:
            logger.debug(f"Failed to send startup self-check: {e}")

    async def _position_sync_loop(self) -> None:
        """Periodically correct follower positions towards leader * ratio, with price gating."""
        if not self.position_manager:
            return

        try:
            if self._position_sync_start_delay_s > 0:
                await asyncio.sleep(float(self._position_sync_start_delay_s))
        except Exception:
            pass

        while self.running:
            try:
                # Don't fight risk halt/stop-loss controls.
                if getattr(self, "_trading_halted", False):
                    await asyncio.sleep(float(self._position_sync_interval_s))
                    continue

                async with self._position_sync_lock:
                    leader_address = str(self.config.get("target_address", "") or "")
                    if not leader_address:
                        await asyncio.sleep(float(self._position_sync_interval_s))
                        continue

                    copy_cfg = self.config.get("copy_trading", {}) or {}
                    copy_mode = str(copy_cfg.get("copy_mode", "position") or "position").strip().lower()
                    copy_ratio = float(copy_cfg.get("copy_ratio", 0.1) or 0.1)
                    min_trade_size = float(copy_cfg.get("min_trade_size", 0.01) or 0.01)
                    max_notional = float(copy_cfg.get("max_notional_per_trade_usd", 0.0) or 0.0)

                    # Wallet mode: position-sync should target the dynamic wallet ratio,
                    # not the static configured copy_ratio.
                    if copy_mode == "wallet":
                        try:
                            follower_balance = await self.position_manager.get_account_value_usd_async()
                            leader_balance = await self.position_manager.get_account_value_usd_async(leader_address)
                            if follower_balance and leader_balance and float(leader_balance) > 0:
                                copy_ratio = float(follower_balance) / float(leader_balance)
                                logger.info(
                                    "💰 Position sync wallet ratio: follower=%.2fU leader=%.2fU ratio=%.4f",
                                    float(follower_balance),
                                    float(leader_balance),
                                    float(copy_ratio),
                                )
                            else:
                                logger.warning(
                                    "💰 Position sync skipped (wallet mode balance unavailable): follower=%s leader=%s",
                                    follower_balance,
                                    leader_balance,
                                )
                                await asyncio.sleep(float(self._position_sync_interval_s))
                                continue
                        except Exception as e:
                            logger.warning(f"💰 Position sync skipped (wallet mode error): {e}")
                            await asyncio.sleep(float(self._position_sync_interval_s))
                            continue

                    # Default leverage for sync opens: env override, otherwise bounded by MAX_LEVERAGE.
                    max_lev = int(copy_cfg.get("max_leverage", 5) or 5)
                    default_lev = int(self._position_sync_default_leverage)
                    default_lev = max(1, min(default_lev, max_lev))

                    report = await self.position_manager.execute_ratio_sync(
                        leader_address=leader_address,
                        copy_ratio=copy_ratio,
                        min_trade_size=min_trade_size,
                        max_notional_per_trade_usd=max_notional,
                        min_notional_usd=float(self._position_sync_min_notional_usd),
                        min_rel_diff=float(self._position_sync_min_rel_diff),
                        allow_worse_pct=float(self._position_sync_allow_worse_pct),
                        gate_reductions=bool(self._position_sync_gate_reductions),
                        default_leverage=int(default_lev),
                        price_ref_mode=str(self._position_sync_price_ref_mode),
                        fill_ref_fallback=str(self._position_sync_fill_ref_fallback),
                        spread_gate_enabled=bool(self._position_sync_spread_gate_enabled),
                        max_spread_bps=float(self._position_sync_max_spread_bps),
                        exclude_recent_trades=self._last_leader_trade_at_by_coin,
                        skip_recent_trade_s=float(self._position_sync_skip_recent_trade_s),
                    )

                    if report.get("status") != "ok":
                        logger.warning(f"Position sync plan failed: {report}")
                        continue

                    submitted = int(report.get("submitted", 0) or 0)
                    skipped = int(report.get("skipped_count", 0) or 0)
                    total_notional = float(report.get("total_notional", 0.0) or 0.0)
                    errors = int(report.get("errors", 0) or 0)

                    if submitted or errors:
                        logger.warning(
                            "🧭 Position sync: submitted=%s errors=%s skipped(price/constraints)=%s total_notional=$%.2f",
                            submitted,
                            errors,
                            skipped,
                            total_notional,
                        )
                    else:
                        logger.info("🧭 Position sync: noop (nothing eligible now)")

                await asyncio.sleep(float(self._position_sync_interval_s))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Position sync loop error: {e}")

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
        logger.info("📞 on_ready callback triggered (WebSocket snapshot received)")
        if not self._catchup_enabled:
            logger.info("⏭️ Catch-up disabled (CATCHUP_ENABLED=false)")
            return
        if not self.running:
            logger.debug("⏭️ Catch-up skipped: not running")
            return
        if not self.use_websocket:
            logger.debug("⏭️ Catch-up skipped: not using websocket")
            return

        if self._catchup_task and not self._catchup_task.done():
            logger.debug("⏭️ Catch-up already in progress")
            return

        async def _runner():
            # Optional delay: if you don't want immediate REST calls on reconnect,
            # wait a bit and let the system stabilize.
            if self._catchup_start_delay_s > 0:
                logger.info(f"⏳ Catch-up delaying {self._catchup_start_delay_s}s before start...")
                await asyncio.sleep(self._catchup_start_delay_s)

            now = time.monotonic()
            time_since_last = now - self._last_catchup_at
            if time_since_last < self._catchup_min_interval_s:
                logger.info(f"⏭️ Catch-up throttled: last run {time_since_last:.1f}s ago (min interval: {self._catchup_min_interval_s}s)")
                return
            self._last_catchup_at = now

            logger.info("🔄 Starting catch-up process...")
            try:
                await self._catch_up_missed_trades_strict_better()
            except Exception as e:
                logger.warning(f"Catch-up skipped due to error: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        self._catchup_task = asyncio.create_task(_runner())

    async def _catch_up_missed_trades_strict_better(self):
        if not self.position_manager or not self.ws_monitor:
            logger.warning("Catch-up skipped: missing position_manager or ws_monitor")
            return

        target = self.config.get('target_address', '')
        if not target:
            logger.warning("Catch-up skipped: no target_address configured")
            return

        # If the network was down for hours, we do NOT try to backfill everything.
        # Only consider a recent bounded window.
        now_ms = int(time.time() * 1000)
        window_ms = int(max(0.0, self._catchup_window_s) * 1000)
        since_ms = max(int(getattr(self.ws_monitor, 'last_check_timestamp', 0) or 0), now_ms - window_ms)

        from datetime import datetime
        since_dt = datetime.fromtimestamp(since_ms / 1000)
        logger.info(f"🔍 Catch-up window: from {since_dt} ({self._catchup_window_s}s)")

        # Fetch current mids once (1 REST call)
        logger.debug("Fetching current market prices...")
        mids = await asyncio.to_thread(self.position_manager.info.all_mids)
        if not isinstance(mids, dict) or not mids:
            logger.warning("Catch-up aborted: failed to fetch market prices")
            return

        # Fetch fills once (1 REST call)
        logger.info(f"📥 Fetching fills for {target}...")
        fills = await asyncio.to_thread(self.position_manager.info.user_fills, target)
        if not fills:
            logger.info("✅ Catch-up complete: no fills found")
            return

        logger.info(f"📊 Found {len(fills)} total fills, filtering...")

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

                raw_hash = fill.get('hash') or fill.get('txHash') or ''
                if not isinstance(raw_hash, str):
                    raw_hash = str(raw_hash)
                tid = fill.get('tid', None)
                if tid is not None and raw_hash:
                    txh = f"{raw_hash}:{tid}"
                elif tid is not None:
                    txh = f"tid:{tid}"
                else:
                    txh = raw_hash

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

                # Determine action: prefer dir to avoid misclassifying CLOSE as OPEN.
                from .trade_monitor import TradeAction
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
                    action = TradeAction.OPEN_LONG if side == 'B' else TradeAction.OPEN_SHORT

                is_open = action in (TradeAction.OPEN_LONG, TradeAction.OPEN_SHORT)
                if is_open:
                    if not getattr(self, '_catchup_replay_opens', False):
                        processed.add(txh)
                        continue

                    # Strictly better only for OPENs:
                    # - If we need to BUY, current mid must be strictly lower.
                    # - If we need to SELL, current mid must be strictly higher.
                    better = (mid < fill_px) if side == 'B' else (mid > fill_px)
                    considered += 1
                    if not better:
                        processed.add(txh)
                        continue
                else:
                    # CLOSEs must be replayed for correctness even if price isn't "better".
                    considered += 1
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
        wallet_info = f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}\n\n" if self.wallet_label or self.account_address else ""
        msg1 = (
            f"🔁 *Catch-up pending* (strict better only)\n\n"
            f"{wallet_info}"
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
            wallet_info = f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}\n\n" if self.wallet_label or self.account_address else ""
            await tg.send_message(f"ℹ️ Re-check result: target has already closed (or is flat). Skipping catch-up.\n\n{wallet_info}")
            return []

        # Re-check current mids and re-filter strictly better *now*.
        filtered = await self._filter_trades_strict_better_now(relevant)
        if not filtered:
            wallet_info = f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}\n\n" if self.wallet_label or self.account_address else ""
            await tg.send_message(f"ℹ️ Re-check result: 0 trades are still strictly better. Skipping catch-up.\n\n{wallet_info}")
            return []

        token2 = secrets.token_hex(3).upper()
        wallet_info = f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}\n\n" if self.wallet_label or self.account_address else ""
        msg2 = (
            f"✅ *Re-check complete* (strict better now)\n\n"
            f"{wallet_info}"
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

        wallet_info = f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}\n\n" if self.wallet_label or self.account_address else ""
        await tg.send_message(f"✅ Catch-up confirmed: `{len(filtered)}` trades will replay slowly\n\n{wallet_info}")
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
                # CLOSE trades are always allowed.
                if getattr(t, 'action', None) in (TradeAction.CLOSE_LONG, TradeAction.CLOSE_SHORT):
                    out.append(t)
                    continue

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
                # CLOSE trades should always be allowed: if the target is flat now,
                # that is precisely when we still need to catch up and close too.
                if getattr(t, 'action', None) in (TradeAction.CLOSE_LONG, TradeAction.CLOSE_SHORT):
                    out.append(t)
                    continue

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
            wallet_info = f"💼 钱包: {self.wallet_label or f'{self.account_address[:6]}...{self.account_address[-4:]}'}\n\n" if self.wallet_label or self.account_address else ""
            await tg.send_message(f"⏱️ Catch-up prompt timed out (no reply): skipping `... {token}`\n\n{wallet_info}")
        except Exception:
            pass
        return None

    def _submit_trade(self, trade: MonitoredTrade):
        """Submit a trade into the burst batcher."""
        try:
            coin = str(getattr(trade, 'coin', '') or '')
            if coin:
                self._last_leader_trade_at_by_coin[coin] = time.monotonic()
        except Exception:
            pass
        self._trade_batcher.submit(trade)

    async def _handle_trade_batch(self, trades: list[MonitoredTrade]):
        """Handle a batch of aggregated trades (per-coin netted)."""
        copy_config = self.config.get('copy_trading', {})
        # One positions refresh per batch (debounced + rate-limited internally)
        if self.position_manager:
            await self.position_manager.update_positions()

        # Stronger guarantee: process CLOSEs before OPENs per coin (reduces flip overlap).
        try:
            priority = {
                TradeAction.CLOSE_LONG: 0,
                TradeAction.CLOSE_SHORT: 0,
                TradeAction.OPEN_LONG: 1,
                TradeAction.OPEN_SHORT: 1,
            }
            trades = sorted(trades, key=lambda t: (str(getattr(t, 'coin', '') or ''), priority.get(getattr(t, 'action', ''), 9)))
        except Exception:
            pass

        for trade in trades:
            await self._handle_new_trade(trade, copy_config)

    async def _handle_new_trade(self, trade: MonitoredTrade, copy_config: Dict[str, Any]):
        """处理新监控到的交易。"""
        start_time = time.time()

        try:
            # Centralized deduplication check
            tx_hash = getattr(trade, 'tx_hash', None)
            if tx_hash and await self._is_trade_processed(tx_hash):
                logger.debug(f"Skipping duplicate trade: {tx_hash}")
                return

            logger.info(f"⚡ Processing new trade: {trade}")

            # Track in-flight to prevent duplicates while executing.
            if tx_hash:
                await self._mark_trade_inflight(tx_hash)

            # 检查是否启用跟单
            if not copy_config.get('enabled', True):
                logger.debug("Copy trading is disabled")
                return

            # Risk halt: stop accepting new trades after an emergency stop-loss.
            if self._trading_halted:
                now = time.time()
                if (now - self._last_halt_log_at) >= 60:
                    logger.warning(f"⛔ Trading halted ({self._trading_halted_reason}); skipping new trades")
                    self._last_halt_log_at = now
                return

            # 获取跟单参数
            copy_mode = copy_config.get('copy_mode', 'position')
            copy_ratio = copy_config.get('copy_ratio', 0.1)
            max_size = copy_config.get('max_position_size', 1.0)
            max_leverage = copy_config.get('max_leverage', 5)
            max_notional = copy_config.get('max_notional_per_trade_usd', 0.0)
            min_trade_size = copy_config.get('min_trade_size', 0.01)
            leader_address = self.config.get('target_address')

            # 执行跟单
            exec_report = await self.position_manager.execute_copy_trade(
                trade,
                copy_ratio,
                max_size,
                max_leverage=max_leverage,
                max_notional_per_trade_usd=max_notional,
                min_trade_size=min_trade_size,
                copy_mode=copy_mode,
                leader_address=leader_address,
            )

            # 计算响应时间
            response_time = time.time() - start_time
            # Avoid false positives: distinguish submitted/skipped/error.
            if isinstance(exec_report, dict):
                st = exec_report.get('status')
                rsn = exec_report.get('reason')
                if st == 'submitted':
                    if rsn:
                        logger.info(f"📨 Trade submitted ({rsn}) in {response_time:.3f}s")
                    else:
                        logger.info(f"📨 Trade submitted in {response_time:.3f}s")
                elif st == 'skipped':
                    logger.info(f"⏭️ Trade skipped ({rsn}) in {response_time:.3f}s")
                elif st == 'error':
                    logger.warning(f"❌ Trade failed ({rsn}) in {response_time:.3f}s")
                else:
                    logger.info(f"ℹ️ Trade handled (status={st} reason={rsn}) in {response_time:.3f}s")
            else:
                logger.info(f"ℹ️ Trade handled in {response_time:.3f}s")

            # Mark as processed only after handling result (allow retry on errors).
            if tx_hash:
                if isinstance(exec_report, dict):
                    status = exec_report.get("status")
                    if status in ("submitted", "skipped"):
                        await self._mark_trade_processed(tx_hash)
                    elif status == "error":
                        await self._clear_trade_inflight(tx_hash)
                else:
                    await self._mark_trade_processed(tx_hash)

            # 发送交易通知
            if self.notification_manager:
                # Prefer the execution report from PositionManager so the
                # notification reflects caps (MAX_POSITION_SIZE) and skips.
                status = None
                reason = None
                requested_size = None
                order_size = None
                capped_by_size = None
                capped_by_notional = None
                rounded_down = None
                sz_decimals = None
                min_trade_size_report = None
                max_notional_report = None
                if isinstance(exec_report, dict):
                    status = exec_report.get('status')
                    reason = exec_report.get('reason')
                    requested_size = exec_report.get('requested_size')
                    order_size = exec_report.get('order_size')
                    capped_by_size = exec_report.get('capped_by_size')
                    capped_by_notional = exec_report.get('capped_by_notional')
                    rounded_down = exec_report.get('rounded_down')
                    sz_decimals = exec_report.get('sz_decimals')
                    min_trade_size_report = exec_report.get('min_trade_size')
                    max_notional_report = exec_report.get('max_notional_per_trade_usd')

                trade_data = {
                    'action': trade.action,
                    'coin': trade.coin,
                    'price': trade.price,
                    'leverage': trade.leverage,
                    'response_time': f"{response_time:.3f}s",
                    'status': status,
                    'reason': reason,
                    # requested_size: leader_size * copy_ratio (before max cap)
                    'requested_size': requested_size,
                    # order_size: after caps / partial close sizing
                    'size': order_size if order_size is not None else (trade.size * copy_ratio),
                    'capped_by_size': capped_by_size,
                    'capped_by_notional': capped_by_notional,
                    'rounded_down': rounded_down,
                    'sz_decimals': sz_decimals,
                    'min_trade_size': min_trade_size_report if min_trade_size_report is not None else min_trade_size,
                    'max_notional_per_trade_usd': max_notional_report if max_notional_report is not None else max_notional,
                    # 包含钱包标识，便于在通知中区分多实例 / 多钱包
                    'wallet_label': self.wallet_label,
                    'account_address': self.account_address,
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
        finally:
            if tx_hash:
                await self._clear_trade_inflight(tx_hash)

    async def _log_status(self):
        """记录当前状态。"""
        try:
            if not self.position_manager:
                return

            summary = self.position_manager.get_positions_summary()
            total_pnl = summary.get('total_pnl', 0.0)
            total_positions = int(summary.get('total_positions', 0) or 0)
            positions = summary.get('positions', []) or []

            # Enrich status with per-position notional in USD (mid price).
            total_notional_usd = 0.0
            try:
                mids = await self.position_manager.get_mid_prices()
            except Exception:
                mids = {}
            for p in positions:
                try:
                    coin = str(p.get('coin', '') or '')
                    size = float(p.get('size', 0.0) or 0.0)
                    mid = float(mids.get(coin, 0.0) or 0.0)
                    notional = abs(size) * mid if mid > 0 else 0.0
                    p['mid_price'] = mid
                    p['notional_usd'] = notional
                    total_notional_usd += notional
                except Exception:
                    continue
            summary['total_notional_usd'] = float(total_notional_usd)

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
                    # 在状态摘要中注入钱包标识，方便通知时直接显示是哪条实例/地址
                    try:
                        summary['wallet_label'] = self.wallet_label
                    except Exception:
                        pass
                    try:
                        summary['account_address'] = self.account_address
                    except Exception:
                        pass
                    await self.notification_manager.notify_status(summary)
                    self._last_status_notification = current_time

            # 检查风险控制（用账户权益计算阈值，避免把比例当成美元）
            account_value = None
            if self.position_manager:
                account_value = self.position_manager.get_account_value_usd()
            await self._check_risk_limits(float(total_pnl), account_value_usd=account_value)

        except Exception as e:
            logger.error(f"Error logging status: {e}")

    async def _check_risk_limits(self, current_pnl: float, account_value_usd: Optional[float] = None):
        """检查风险限制。

        Notes:
        - 配置里的 max_drawdown / stop_loss_ratio 语义是"比例"（例如 0.1=10%），
          之前误当成"美元"导致阈值极小（$0.10 / $0.05）。
        - 为兼容老配置：如果值 > 1，则按"绝对美元"处理。
        """
        risk_config = self.config.get('risk_management', {})

        def _to_usd_threshold(v: float, base: Optional[float]) -> Optional[float]:
            try:
                v = float(v)
            except Exception:
                return None
            if v <= 0:
                return None
            # Validate base is within reasonable bounds to prevent overflow
            if base is not None:
                try:
                    base_float = float(base)
                    if base_float < 0 or base_float > 1e15:  # Sanity check: max $1 quadrillion
                        logger.warning(f"Account value out of reasonable bounds: {base_float}")
                        return None
                except (ValueError, OverflowError):
                    logger.warning(f"Invalid account value: {base}")
                    return None
            # Treat <=1 as ratio if we have a base.
            if v <= 1.0:
                if base is None or base <= 0:
                    return None
                return float(base) * v
            # Treat >1 as absolute USD.
            return v

        now = time.time()
        def _can_alert(key: str) -> bool:
            last = self._last_risk_alert_at.get(key, 0.0)
            if (now - last) >= self._risk_alert_min_interval_s:
                self._last_risk_alert_at[key] = now
                return True
            return False

        def _can_act(key: str, min_interval_s: float) -> bool:
            last = self._last_risk_alert_at.get(key, 0.0)
            if (now - last) >= float(min_interval_s):
                self._last_risk_alert_at[key] = now
                return True
            return False

        # 检查最大回撤
        max_drawdown_cfg = float(risk_config.get('max_drawdown', 0.1))
        max_dd_usd = _to_usd_threshold(max_drawdown_cfg, account_value_usd)
        if max_dd_usd is not None and current_pnl < -max_dd_usd:
            if _can_alert('max_drawdown_log'):
                logger.warning(f"Max drawdown exceeded: {current_pnl} < -{max_dd_usd} (cfg={max_drawdown_cfg}, equity={account_value_usd})")
            else:
                logger.debug(f"Max drawdown exceeded: {current_pnl} < -{max_dd_usd} (cfg={max_drawdown_cfg}, equity={account_value_usd})")

            if self.notification_manager and _can_alert('max_drawdown'):
                extra = ""
                if account_value_usd is not None and account_value_usd > 0 and max_drawdown_cfg <= 1.0:
                    extra = f"\n账户权益: ${account_value_usd:.2f} (阈值={max_drawdown_cfg*100:.1f}%)"
                await self.notification_manager.notify_alert(
                    "warning",
                    f"⚠️ 最大回撤超限!\n当前亏损: ${current_pnl:.2f}\n回撤限制: ${max_dd_usd:.2f}{extra}",
                )

        # 检查止损
        stop_loss_cfg = float(risk_config.get('stop_loss_ratio', 0.05))
        stop_loss_usd = _to_usd_threshold(stop_loss_cfg, account_value_usd)
        if stop_loss_usd is not None and current_pnl < -stop_loss_usd:
            if _can_alert('stop_loss_log'):
                logger.warning(f"Stop loss triggered: {current_pnl} < -{stop_loss_usd} (cfg={stop_loss_cfg}, equity={account_value_usd})")
            else:
                logger.debug(f"Stop loss triggered: {current_pnl} < -{stop_loss_usd} (cfg={stop_loss_cfg}, equity={account_value_usd})")

            if self.notification_manager and _can_alert('stop_loss'):
                extra = ""
                if account_value_usd is not None and account_value_usd > 0 and stop_loss_cfg <= 1.0:
                    extra = f"\n账户权益: ${account_value_usd:.2f} (阈值={stop_loss_cfg*100:.1f}%)"
                await self.notification_manager.notify_alert(
                    "error",
                    f"🚨 止损触发!\n当前亏损: ${current_pnl:.2f}\n止损线: ${stop_loss_usd:.2f}{extra}\n建议立即检查!",
                )

            # Optional execution: auto-flatten and halt (prevents churn / loops).
            if self._risk_auto_close_on_stop_loss and self.position_manager:
                if (not self._stop_loss_exec_in_progress) and _can_act('stop_loss_exec', self._risk_auto_close_cooldown_s):
                    await self._execute_stop_loss(current_pnl=current_pnl, stop_loss_usd=float(stop_loss_usd))

    async def _execute_stop_loss(self, *, current_pnl: float, stop_loss_usd: float) -> None:
        """Emergency action when stop-loss triggers.

        Best-effort: attempt to market-close all positions, then optionally halt trading / stop the bot.
        Uses a lock + cooldown to avoid repeated loops.
        """
        if not self.position_manager:
            return

        if self._stop_loss_exec_in_progress:
            return
        self._stop_loss_exec_in_progress = True
        self._last_stop_loss_exec_at = time.time()

        try:
            # Force-refresh positions so we close real sizes.
            try:
                await self.position_manager.update_positions(force=True, ignore_backoff=True)
            except Exception:
                pass

            report = await self.position_manager.close_all_positions()
            logger.warning(f"🧯 Stop-loss auto-close submitted: pnl={current_pnl:.2f} threshold={stop_loss_usd:.2f} report={report}")

            # Halt trading to avoid immediately re-opening via new leader fills.
            if self._risk_halt_trading_on_stop_loss:
                self._trading_halted = True
                self._trading_halted_reason = "stop_loss"

            # Notify once (throttled by existing stop_loss key)
            if self.notification_manager:
                try:
                    await self.notification_manager.notify_alert(
                        "error",
                        "🧯 已执行止损自动平仓（Auto-close）\n"
                        f"当前亏损: ${current_pnl:.2f}\n"
                        f"止损线: ${stop_loss_usd:.2f}\n"
                        f"结果: {report}",
                    )
                except Exception:
                    pass

            # Optional: stop the bot after flatten.
            if self._risk_auto_close_and_stop:
                self.running = False
        finally:
            self._stop_loss_exec_in_progress = False

    async def _auto_flatten_on_stop_loss(
        self,
        current_pnl: float,
        stop_loss_usd: float,
        stop_loss_cfg: float,
        account_value_usd: Optional[float],
    ) -> None:
        if not self.position_manager:
            return

        if self._risk_close_lock.locked():
            logger.warning("Stop-loss auto-close skipped (already in progress)")
            return

        async with self._risk_close_lock:
            try:
                # Force-refresh positions once before flattening (best effort).
                try:
                    await self.position_manager.update_positions(force=True, ignore_backoff=True)
                except Exception as e:
                    logger.warning(f"Stop-loss auto-close: forced refresh failed: {e}")

                report = await self.position_manager.close_all_positions()
                closed = report.get('closed', []) if isinstance(report, dict) else []
                errors = int(report.get('errors', 0) or 0) if isinstance(report, dict) else 0

                logger.warning(
                    "Stop-loss auto-close executed: pnl=%s stop_loss_usd=%s cfg=%s equity=%s closed=%s errors=%s",
                    float(current_pnl),
                    float(stop_loss_usd),
                    float(stop_loss_cfg),
                    account_value_usd,
                    len(closed) if isinstance(closed, list) else 0,
                    errors,
                )

                if self.notification_manager:
                    # Keep message compact.
                    lines = [
                        "🧯 *止损自动平仓已执行*",
                        f"当前亏损: `${current_pnl:.2f}`",
                        f"止损线: `${stop_loss_usd:.2f}` (cfg={stop_loss_cfg})",
                    ]
                    if account_value_usd is not None and account_value_usd > 0 and stop_loss_cfg <= 1.0:
                        lines.append(f"账户权益: `${account_value_usd:.2f}`")
                    if isinstance(closed, list) and closed:
                        lines.append("\n已提交平仓:")
                        for item in closed[:10]:
                            try:
                                coin = item.get('coin')
                                csz = float(item.get('closed', 0.0) or 0.0)
                                req = float(item.get('requested', 0.0) or 0.0)
                                lines.append(f"- {coin}: {csz:.6g} / {req:.6g}")
                            except Exception:
                                continue
                        if len(closed) > 10:
                            lines.append(f"... 还有 {len(closed) - 10} 个")
                    if errors:
                        lines.append(f"\n⚠️ 平仓过程中有 {errors} 个错误（详见日志）")
                    await self.notification_manager.notify_alert("error", "\n".join(lines))

            except Exception as e:
                logger.error(f"Stop-loss auto-close failed: {e}")
                if self.notification_manager:
                    try:
                        await self.notification_manager.notify_alert("error", f"🚨 止损自动平仓失败: {str(e)}")
                    except Exception:
                        pass
