"""Main Copy Trader implementation for Hyperliquid.

整合交易监控和仓位管理，实现自动跟单功能。
"""
import asyncio
import logging
import signal
import sys
from typing import Dict, Any, Optional
import yaml
import os

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .trade_monitor import TradeMonitor, MonitoredTrade
from .position_manager import PositionManager
from .notifications import NotificationManager

logger = logging.getLogger(__name__)


class HyperliquidCopyTrader:
    """Hyperliquid 自动跟单交易器。

    监控指定地址的交易并自动复制到自己的账户。
    """

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.running = False

        # 初始化组件
        self.trade_monitor: Optional[TradeMonitor] = None
        self.position_manager: Optional[PositionManager] = None
        self.notification_manager: Optional[NotificationManager] = None

        # 初始化 Hyperliquid 客户端
        self._init_hyperliquid_clients()

        # 初始化通知管理器
        self._init_notifications()

        logger.info("✅ HyperliquidCopyTrader initialized")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件。"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded config from {config_path}")
        return config

    def _init_hyperliquid_clients(self):
        """初始化 Hyperliquid 客户端。"""
        hl_config = self.config.get('hyperliquid', {})
        use_testnet = hl_config.get('use_testnet', False)

        # 设置基础 URL
        base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL

        # 初始化信息客户端
        info_client = Info(base_url=base_url)

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

            self.trade_monitor = TradeMonitor(target_address, use_testnet, exclude_addresses)
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

        # 设置信号处理
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, stopping...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # 启动监控循环
            await self._monitoring_loop()

        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            # 发送关闭通知
            if self.notification_manager:
                await self.notification_manager.notify_shutdown()
                await self.notification_manager.close()

            logger.info("🛑 Hyperliquid Copy Trader stopped")

    async def stop(self):
        """停止跟单交易器。"""
        self.running = False
        logger.info("Stopping Hyperliquid Copy Trader")

    async def _monitoring_loop(self):
        """主监控循环。"""
        copy_config = self.config.get('copy_trading', {})
        poll_interval = self.config.get('monitoring', {}).get('poll_interval', 30)

        logger.info(f"Starting monitoring loop with {poll_interval}s interval")

        while self.running:
            try:
                # 更新仓位信息
                await self.position_manager.update_positions()

                # 检查新交易
                trades = await self.trade_monitor.get_recent_trades()

                # 处理每个新交易
                for trade in trades:
                    await self._handle_new_trade(trade, copy_config)

                # 记录状态
                await self._log_status()

                # 等待下次检查
                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(poll_interval)

    async def _handle_new_trade(self, trade: MonitoredTrade, copy_config: Dict[str, Any]):
        """处理新监控到的交易。"""
        try:
            logger.info(f"Processing new trade: {trade}")

            # 检查是否启用跟单
            if not copy_config.get('enabled', True):
                logger.debug("Copy trading is disabled")
                return

            # 获取跟单参数
            copy_ratio = copy_config.get('copy_ratio', 0.1)
            max_size = copy_config.get('max_position_size', 1.0)

            # 执行跟单
            await self.position_manager.execute_copy_trade(trade, copy_ratio, max_size)

            # 发送交易通知
            if self.notification_manager:
                trade_data = {
                    'action': trade.action,
                    'coin': trade.coin,
                    'size': trade.size * copy_ratio,  # 实际跟单大小
                    'price': trade.price,
                    'leverage': trade.leverage
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
            summary = self.position_manager.get_positions_summary()
            total_pnl = summary['total_pnl']

            logger.info(f"Status: {summary['total_positions']} positions, "
                       f"Total PnL: ${total_pnl:.2f}")

            # 发送状态通知 (每小时一次或有重要变化时)
            if self.notification_manager:
                await self.notification_manager.notify_status(summary)

            # 检查风险控制
            await self._check_risk_limits(total_pnl)

        except Exception as e:
            logger.error(f"Error logging status: {e}")

    async def _check_risk_limits(self, current_pnl: float):
        """检查风险限制。"""
        risk_config = self.config.get('risk_management', {})

        # 检查最大回撤
        max_drawdown = risk_config.get('max_drawdown', 0.1)
        if current_pnl < -max_drawdown:
            logger.warning(f"Max drawdown exceeded: {current_pnl} < -{max_drawdown}")

            # 发送风险警报
            if self.notification_manager:
                await self.notification_manager.notify_alert(
                    "warning",
                    f"⚠️ 最大回撤超限!\n当前亏损: ${current_pnl:.2f}\n回撤限制: ${max_drawdown:.2f}"
                )

            # 这里可以实现自动停止或报警逻辑

        # 检查止损
        stop_loss_ratio = risk_config.get('stop_loss_ratio', 0.05)
        if current_pnl < -stop_loss_ratio:
            logger.warning(f"Stop loss triggered: {current_pnl} < -{stop_loss_ratio}")

            # 发送止损警报
            if self.notification_manager:
                await self.notification_manager.notify_alert(
                    "error",
                    f"🚨 止损触发!\n当前亏损: ${current_pnl:.2f}\n止损线: ${stop_loss_ratio:.2f}\n建议立即检查!"
                )

            # 实现止损逻辑