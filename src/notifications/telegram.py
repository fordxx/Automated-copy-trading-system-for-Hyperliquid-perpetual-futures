"""Telegram Notification Module for Hyperliquid Copy Trader.

提供Telegram机器人通知功能，实时推送交易信息。
"""
import asyncio
import logging
from typing import Dict, Any, Optional
import aiohttp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram通知器。

    使用Telegram Bot API发送通知消息。
    """

    def __init__(self, bot_token: str, chat_id: str):
        """初始化Telegram通知器。

        Args:
            bot_token: Telegram机器人令牌
            chat_id: 聊天ID（用户ID或群组ID）
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.session: Optional[aiohttp.ClientSession] = None

        logger.info("✅ Telegram notifier initialized")

    async def initialize(self):
        """初始化HTTP会话。"""
        if not self.session or self.session.closed:
            # Close old session if it exists but is closed
            if self.session and self.session.closed:
                try:
                    await self.session.close()
                except Exception:
                    pass
            try:
                self.session = aiohttp.ClientSession()
            except Exception as e:
                logger.error(f"Failed to create aiohttp session: {e}")
                self.session = None
                raise

    async def close(self):
        """关闭HTTP会话。"""
        if self.session:
            try:
                await self.session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
            finally:
                self.session = None

    async def send_message(self, message: str, parse_mode: Optional[str] = None) -> bool:
        """发送消息到Telegram。

        Args:
            message: 消息内容
            parse_mode: 解析模式 (None for plain text, "Markdown", "HTML", etc.)

        Returns:
            发送是否成功
        """
        if not self.session:
            await self.initialize()

        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "disable_web_page_preview": True
            }
            if parse_mode:
                data["parse_mode"] = parse_mode

            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    logger.debug(f"Telegram message sent: {message[:50]}...")
                    return True
                else:
                    error_data = await response.json()
                    logger.error(f"Failed to send Telegram message: {error_data}")
                    return False

        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    async def get_updates(self, offset: Optional[int] = None, timeout_s: int = 30) -> list[dict]:
        """Fetch incoming updates for this bot via long polling.

        This enables simple operator-in-the-loop approvals (reply YES/NO).

        Args:
            offset: Telegram update offset (use last_update_id + 1 to avoid old updates)
            timeout_s: Long-poll timeout in seconds

        Returns:
            List of update dicts.
        """
        if not self.session:
            await self.initialize()

        try:
            url = f"{self.base_url}/getUpdates"
            params: dict[str, Any] = {
                "timeout": int(max(0, timeout_s)),
                "allowed_updates": ["message"],
            }
            if offset is not None:
                params["offset"] = int(offset)

            async with self.session.get(url, params=params) as response:
                data = await response.json()
                if not data.get("ok"):
                    logger.error(f"Failed to get Telegram updates: {data}")
                    return []
                result = data.get("result")
                if isinstance(result, list):
                    return result
                return []
        except Exception as e:
            logger.error(f"Error getting Telegram updates: {e}")
            return []

    async def send_trade_notification(self, trade_data: Dict[str, Any]):
        """发送交易通知。

        Args:
            trade_data: 交易数据字典
        """
        try:
            action = trade_data.get('action', 'unknown')
            coin = trade_data.get('coin', 'unknown')
            size = trade_data.get('size', 0)
            requested_size = trade_data.get('requested_size')
            price = trade_data.get('price', 0)
            pnl = trade_data.get('pnl', 0)
            status = trade_data.get('status')
            reason = trade_data.get('reason')
            capped_by_notional = trade_data.get('capped_by_notional')
            capped_by_size = trade_data.get('capped_by_size')
            max_notional_per_trade_usd = trade_data.get('max_notional_per_trade_usd')
            rounded_down = trade_data.get('rounded_down')
            sz_decimals = trade_data.get('sz_decimals')
            min_trade_size = trade_data.get('min_trade_size')

            # 构建消息
            emoji = "🟢" if action in ['open_long', 'close_short'] else "🔴"
            action_text = {
                'open_long': '开多',
                'open_short': '开空',
                'close_long': '平多',
                'close_short': '平空'
            }.get(action, action.upper())

            message = f"{emoji} 交易通知\n\n"
            message += f"📊 操作: {action_text}\n"
            message += f"🪙 币种: {coin}\n"
            # If we have both requested and actual, show both to avoid confusion.
            try:
                size_f = float(size)
            except Exception:
                size_f = 0.0

            if requested_size is not None:
                try:
                    req_f = float(requested_size)
                except Exception:
                    req_f = None
                if req_f is not None:
                    message += f"📈 计划数量: {req_f:.4f}\n"
                    message += f"✅ 实际数量: {size_f:.4f}\n"
                else:
                    message += f"📈 数量: {size_f:.4f}\n"
            else:
                message += f"📈 数量: {size_f:.4f}\n"

            # Explain why actual size differs from planned size.
            cap_notes: list[str] = []
            try:
                if capped_by_notional is True and max_notional_per_trade_usd is not None:
                    cap_notes.append(f"已按名义上限 ${float(max_notional_per_trade_usd):.0f} 截断")
            except Exception:
                if capped_by_notional is True:
                    cap_notes.append("已按名义上限截断")
            if capped_by_size is True:
                cap_notes.append("已按合约数量上限截断")
            if rounded_down is True:
                if sz_decimals is not None:
                    cap_notes.append(f"已按精度向下取整 (szDecimals={int(sz_decimals)})")
                else:
                    cap_notes.append("已按精度向下取整")
            if cap_notes:
                message += f"✂️ 调整: {'；'.join(cap_notes)}\n"

            message += f"💰 价格: ${price:.2f}\n"

            if status:
                status_text = {
                    'submitted': '已提交',
                    'executed': '已执行',
                    'skipped': '已跳过',
                    'error': '失败',
                }.get(str(status), str(status))
                message += f"🧾 结果: {status_text}\n"
                if reason:
                    reason_text = {
                        'no_follower_position': '跟单账户无对应仓位，无法平仓',
                        'too_small': '数量过小',
                    }.get(str(reason), str(reason))
                    message += f"📝 原因: {reason_text}\n"

                    if str(reason) == 'too_small' and min_trade_size is not None:
                        try:
                            message += f"🔎 阈值: MIN_TRADE_SIZE={float(min_trade_size):g}\n"
                        except Exception:
                            message += f"🔎 阈值: MIN_TRADE_SIZE={min_trade_size}\n"

            if pnl != 0:
                pnl_emoji = "📈" if pnl > 0 else "📉"
                message += f"{pnl_emoji} 盈亏: ${pnl:.2f}\n"

            await self.send_message(message)

        except Exception as e:
            logger.error(f"Error sending trade notification: {e}")

    async def send_status_notification(self, status_data: Dict[str, Any]):
        """发送状态通知。

        Args:
            status_data: 状态数据字典
        """
        try:
            total_positions = status_data.get('total_positions', 0)
            total_pnl = status_data.get('total_pnl', 0)

            message = f"📊 状态报告\n\n"
            message += f"📂 持仓数量: {total_positions}\n"
            message += f"💰 总盈亏: ${total_pnl:.2f}\n"

            positions = status_data.get('positions', [])
            if positions:
                message += "\n📋 持仓详情:\n"
                for pos in positions[:5]:  # 只显示前5个
                    direction = "多头" if pos.get('size', 0) > 0 else "空头"
                    message += f"• {pos.get('coin')} {direction}: {abs(pos.get('size', 0)):.4f} @ ${pos.get('entry_price', 0):.2f}\n"

            await self.send_message(message)

        except Exception as e:
            logger.error(f"Error sending status notification: {e}")

    async def send_alert_notification(self, alert_type: str, message: str):
        """发送警报通知。

        Args:
            alert_type: 警报类型
            message: 警报消息
        """
        try:
            emoji_map = {
                'error': '❌',
                'warning': '⚠️',
                'info': 'ℹ️',
                'success': '✅'
            }

            emoji = emoji_map.get(alert_type.lower(), '🔔')
            full_message = f"{emoji} {alert_type.upper()}\n\n{message}"

            await self.send_message(full_message)

        except Exception as e:
            logger.error(f"Error sending alert notification: {e}")

    async def send_startup_notification(self):
        """发送启动通知。"""
        message = "🚀 Hyperliquid Copy Trader 已启动\n\n"
        message += "系统正在监控目标地址的交易活动..."
        await self.send_message(message)

    async def send_shutdown_notification(self):
        """发送关闭通知。"""
        message = "🛑 Hyperliquid Copy Trader 已停止\n\n"
        message += "系统已安全关闭。"
        await self.send_message(message)


class NotificationManager:
    """通知管理器。

    统一管理各种通知渠道。
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.telegram: Optional[TelegramNotifier] = None

        self._initialize_notifiers()

    def _initialize_notifiers(self):
        """初始化通知器。"""
        telegram_config = self.config.get('telegram', {})

        if telegram_config.get('enabled', False):
            bot_token = telegram_config.get('bot_token')
            chat_id = telegram_config.get('chat_id')

            if bot_token and chat_id:
                self.telegram = TelegramNotifier(bot_token, chat_id)
                logger.info("✅ Telegram notifications enabled")
            else:
                logger.warning("⚠️ Telegram enabled but missing bot_token or chat_id")

    async def initialize(self):
        """初始化所有通知器。"""
        if self.telegram:
            await self.telegram.initialize()

    async def close(self):
        """关闭所有通知器。"""
        if self.telegram:
            await self.telegram.close()

    async def notify_trade(self, trade_data: Dict[str, Any]):
        """通知交易事件。"""
        if self.telegram:
            await self.telegram.send_trade_notification(trade_data)

    async def notify_status(self, status_data: Dict[str, Any]):
        """通知状态更新。"""
        if self.telegram:
            await self.telegram.send_status_notification(status_data)

    async def notify_alert(self, alert_type: str, message: str):
        """发送警报。"""
        if self.telegram:
            await self.telegram.send_alert_notification(alert_type, message)

    async def notify_startup(self):
        """通知系统启动。"""
        if self.telegram:
            await self.telegram.send_startup_notification()

    async def notify_shutdown(self):
        """通知系统关闭。"""
        if self.telegram:
            await self.telegram.send_shutdown_notification()