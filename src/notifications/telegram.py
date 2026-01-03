"""Telegram Notification Module for Hyperliquid Copy Trader.

提供Telegram机器人通知功能，实时推送交易信息。
"""
import asyncio
import logging
import os
import time
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

        # Noise reduction: throttle repeated skipped trade notifications (e.g. many CLOSEs after already flat).
        try:
            self._skipped_trade_throttle_s = float(os.getenv("TELEGRAM_SKIPPED_TRADE_THROTTLE_S", "300") or 300)
        except Exception:
            self._skipped_trade_throttle_s = 300.0
        self._skipped_trade_last_sent_at: Dict[str, float] = {}
        self._skipped_trade_suppressed_count: Dict[str, int] = {}

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

    async def set_my_commands(self) -> bool:
        """设置机器人命令列表。

        Returns:
            是否设置成功
        """
        if not self.session:
            await self.initialize()

        try:
            url = f"{self.base_url}/setMyCommands"
            commands = [
                {"command": "help", "description": "显示帮助信息"},
                {"command": "status", "description": "查看当前状态"},
                {"command": "wallets", "description": "列出所有钱包实例"},
                {"command": "pause", "description": "暂停跟单"},
                {"command": "resume", "description": "恢复跟单"},
                {"command": "pnl", "description": "显示盈亏"},
                {"command": "positions", "description": "显示当前持仓"},
            ]
            data = {"commands": commands}

            async with self.session.post(url, json=data) as response:
                result = await response.json()
                if result.get("ok"):
                    logger.info("✅ Telegram commands registered")
                    return True
                else:
                    logger.error(f"Failed to set commands: {result}")
                    return False
        except Exception as e:
            logger.error(f"Error setting Telegram commands: {e}")
            return False

    def parse_command(self, text: str) -> Optional[tuple[str, str]]:
        """解析命令。

        Args:
            text: 消息文本

        Returns:
            (command, args) 或 None 如果不是命令
        """
        if not text or not text.startswith("/"):
            return None
        
        parts = text.split(" ", 1)
        command = parts[0][1:]  # 移除 /
        args = parts[1] if len(parts) > 1 else ""
        return command, args

    async def reply_to_message(self, message_id: int, reply_text: str) -> bool:
        """回复消息。

        Args:
            message_id: 要回复的消息ID
            reply_text: 回复文本

        Returns:
            是否发送成功
        """
        if not self.session:
            await self.initialize()

        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": reply_text,
                "reply_to_message_id": message_id,
                "disable_web_page_preview": True
            }

            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    logger.debug(f"Reply sent to message {message_id}")
                    return True
                else:
                    error_data = await response.json()
                    logger.error(f"Failed to send reply: {error_data}")
                    return False
        except Exception as e:
            logger.error(f"Error sending reply: {e}")
            return False

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
            wallet_label = trade_data.get('wallet_label')
            account_address = trade_data.get('account_address')

            # 构建消息
            emoji = "🟢" if action in ['open_long', 'close_short'] else "🔴"
            action_text = {
                'open_long': '开多',
                'open_short': '开空',
                'close_long': '平多',
                'close_short': '平空'
            }.get(action, action.upper())

            message = f"{emoji} 交易通知\n\n"
            # 显示钱包标识（优先使用实例名称，其次使用地址简写）
            if wallet_label:
                message += f"💼 钱包: {wallet_label}\n"
            elif account_address:
                addr_short = f"{account_address[:6]}...{account_address[-4:]}"
                message += f"💼 钱包: {addr_short}\n"
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

            # Throttle noisy skipped notifications.
            # We still show an occasional aggregated message so you know it's happening.
            try:
                if str(status) == 'skipped' and str(reason) in ('no_follower_position', 'too_small'):
                    key = f"{coin}:{str(reason)}"
                    now = time.monotonic()
                    last = float(self._skipped_trade_last_sent_at.get(key, 0.0) or 0.0)
                    self._skipped_trade_suppressed_count[key] = int(self._skipped_trade_suppressed_count.get(key, 0) or 0) + 1

                    if float(self._skipped_trade_throttle_s) > 0 and (now - last) < float(self._skipped_trade_throttle_s):
                        return

                    suppressed = int(self._skipped_trade_suppressed_count.get(key, 0) or 0)
                    self._skipped_trade_last_sent_at[key] = now
                    self._skipped_trade_suppressed_count[key] = 0
                    if suppressed > 1:
                        message += f"🔕 已合并跳过通知: {suppressed} 次/{int(self._skipped_trade_throttle_s)}s\n"
            except Exception:
                pass

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
            total_notional = status_data.get('total_notional_usd')
            wallet_label = status_data.get('wallet_label')
            account_address = status_data.get('account_address')

            message = f"📊 状态报告\n\n"
            # 显示钱包标识（优先使用实例名称，其次使用地址简写）
            if wallet_label:
                message += f"💼 钱包: {wallet_label}\n"
            elif account_address:
                addr_short = f"{account_address[:6]}...{account_address[-4:]}"
                message += f"💼 钱包: {addr_short}\n"
            message += f"📂 持仓数量: {total_positions}\n"
            message += f"💰 总盈亏: ${total_pnl:.2f}\n"
            if total_notional is not None:
                try:
                    message += f"🧾 持仓名义: ${float(total_notional):.2f}\n"
                except Exception:
                    pass

            positions = status_data.get('positions', [])
            if positions:
                message += "\n📋 持仓详情:\n"
                # Prefer sorting by notional desc when provided.
                try:
                    positions = sorted(positions, key=lambda p: float(p.get('notional_usd', 0) or 0), reverse=True)
                except Exception:
                    pass

                lines: list[str] = []
                for pos in positions:
                    try:
                        coin = str(pos.get('coin', '') or '')
                        size = float(pos.get('size', 0) or 0)
                        direction = "多头" if size > 0 else "空头"
                        entry = float(pos.get('entry_price', 0) or 0)
                        mid = float(pos.get('mid_price', 0) or 0)
                        notional = float(pos.get('notional_usd', 0) or 0)
                        lines.append(f"• {coin} {direction}: {abs(size):.4f} @ ${entry:.4f} | 现价 ${mid:.4f} | ≈${notional:.2f}")
                    except Exception:
                        direction = "多头" if pos.get('size', 0) > 0 else "空头"
                        lines.append(f"• {pos.get('coin')} {direction}: {abs(pos.get('size', 0)):.4f} @ ${pos.get('entry_price', 0):.2f}")

                # Telegram text limit is ~4096 chars. Chunk to be safe.
                max_len = 3800
                chunk = message
                sent_any = False
                for line in lines:
                    if len(chunk) + len(line) + 1 > max_len:
                        await self.send_message(chunk)
                        sent_any = True
                        chunk = "📊 状态报告（续）\n\n" + line + "\n"
                    else:
                        chunk += line + "\n"
                if chunk.strip():
                    await self.send_message(chunk)
                elif not sent_any:
                    await self.send_message(message)
            else:
                await self.send_message(message)

        except Exception as e:
            logger.error(f"Error sending status notification: {e}")

    async def send_alert_notification(
        self, 
        alert_type: str, 
        message: str,
        wallet_label: Optional[str] = None,
        account_address: Optional[str] = None,
    ):
        """发送警报通知。

        Args:
            alert_type: 警报类型
            message: 警报消息
            wallet_label: 钱包标识
            account_address: 钱包地址
        """
        try:
            emoji_map = {
                'error': '❌',
                'warning': '⚠️',
                'info': 'ℹ️',
                'success': '✅'
            }

            emoji = emoji_map.get(alert_type.lower(), '🔔')
            full_message = f"{emoji} {alert_type.upper()}\n\n"
            
            # 显示钱包标识
            if wallet_label:
                full_message += f"💼 钱包: {wallet_label}\n"
            elif account_address:
                addr_short = f"{account_address[:6]}...{account_address[-4:]}"
                full_message += f"💼 钱包: {addr_short}\n"
            
            if wallet_label or account_address:
                full_message += "\n"
            
            full_message += message

            await self.send_message(full_message)

        except Exception as e:
            logger.error(f"Error sending alert notification: {e}")

    async def send_startup_notification(
        self,
        target_address: Optional[str] = None,
        follower_address: Optional[str] = None,
        wallet_label: Optional[str] = None,
        account_address: Optional[str] = None,
    ):
        """发送启动通知。"""
        message = "🚀 Hyperliquid Copy Trader 已启动\n\n"
        
        # 显示钱包标识
        if wallet_label:
            message += f"💼 钱包: {wallet_label}\n"
        if account_address:
            addr_short = f"{account_address[:6]}...{account_address[-4:]}"
            message += f"📍 地址: {addr_short}\n"
        
        if target_address:
            message += f"🎯 目标地址: {target_address}\n"
        if follower_address:
            message += f"👣 跟随地址: {follower_address}\n"
        if wallet_label or account_address or target_address or follower_address:
            message += "\n"
        message += "系统正在监控目标地址的交易活动..."
        await self.send_message(message)

    async def send_shutdown_notification(
        self,
        wallet_label: Optional[str] = None,
        account_address: Optional[str] = None,
    ):
        """发送关闭通知。"""
        message = "🛑 Hyperliquid Copy Trader 已停止\n\n"
        
        # 显示钱包标识
        if wallet_label:
            message += f"💼 钱包: {wallet_label}\n"
        if account_address:
            addr_short = f"{account_address[:6]}...{account_address[-4:]}"
            message += f"📍 地址: {addr_short}\n"
        
        if wallet_label or account_address:
            message += "\n"
        message += "系统已安全关闭。"
        await self.send_message(message)


class NotificationManager:
    """通知管理器。

    统一管理各种通知渠道。
    """

    def __init__(self, config: Dict[str, Any], wallet_label: str = "", account_address: str = ""):
        self.config = config
        self.wallet_label = wallet_label
        self.account_address = account_address
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
            await self.telegram.send_alert_notification(
                alert_type, 
                message,
                wallet_label=self.wallet_label if self.wallet_label else None,
                account_address=self.account_address if self.account_address else None,
            )

    async def notify_startup(self):
        """通知系统启动。"""
        if self.telegram:
            target = str(self.config.get("target_address", "") or "").strip()
            follower = str(self.config.get("hyperliquid", {}).get("account_address", "") or "").strip()
            await self.telegram.send_startup_notification(
                target_address=target if target else None,
                follower_address=follower if follower else None,
                wallet_label=self.wallet_label if self.wallet_label else None,
                account_address=self.account_address if self.account_address else None,
            )

    async def notify_shutdown(self):
        """通知系统关闭。"""
        if self.telegram:
            await self.telegram.send_shutdown_notification(
                wallet_label=self.wallet_label if self.wallet_label else None,
                account_address=self.account_address if self.account_address else None,
            )

    async def register_commands(self):
        """注册机器人命令。"""
        if self.telegram:
            await self.telegram.set_my_commands()

    def parse_command(self, text: str) -> Optional[tuple[str, str]]:
        """解析命令。"""
        if self.telegram:
            return self.telegram.parse_command(text)
        return None

    async def reply_to_command(self, message_id: int, reply_text: str) -> bool:
        """回复命令消息。"""
        if self.telegram:
            return await self.telegram.reply_to_message(message_id, reply_text)
        return False

    def set_command_handler(self, handler):
        """设置命令处理器。
        
        Args:
            handler: 异步函数，接收 (command, args) 返回响应文本
        """
        self.command_handler = handler

    async def handle_command(self, command: str, args: str) -> str:
        """处理命令。
        
        Args:
            command: 命令名称
            args: 命令参数（可以是钱包实例名称或为空表示全部）
            
        Returns:
            命令响应文本
        """
        if hasattr(self, 'command_handler') and self.command_handler:
            return await self.command_handler(command, args, self.wallet_label, self.account_address)
        
        # 解析目标钱包
        target_wallet = args.strip() if args.strip() else "all"
        wallet_info = f" ({self.wallet_label or self.account_address})" if target_wallet != "all" else " (所有钱包)"
        
        # 默认命令响应
        if command == "help":
            return (
                "🤖 *Hyperliquid Copy Trader 帮助*\n\n"
                "*可用命令：*\n"
                "• /help - 显示此帮助信息\n"
                "• /status [钱包] - 查看状态（无参数=全部）\n"
                "• /wallets - 列出所有钱包\n"
                "• /pause [钱包] - 暂停跟单\n"
                "• /resume [钱包] - 恢复跟单\n"
                "• /pnl [钱包] - 显示盈亏\n"
                "• /positions [钱包] - 显示持仓\n\n"
                "*使用示例：*\n"
                "• /pause - 暂停全部钱包\n"
                "• /pause wallet_1 - 仅暂停wallet_1"
            )
        elif command == "status":
            return f"📊 状态：运行中{wallet_info}\n💼 钱包：{self.wallet_label or self.account_address or 'Unknown'}"
        elif command == "pause":
            return f"⏸️ 已暂停{wallet_info}"
        elif command == "resume":
            return f"▶️ 已恢复{wallet_info}"
        elif command == "pnl":
            return f"💰 获取盈亏数据{wallet_info}..."
        elif command == "positions":
            return f"📋 获取持仓数据{wallet_info}..."
        elif command == "wallets":
            return "👛 所有钱包实例已列出"
        else:
            return f"❓ 未知命令：/{command}\n输入 /help 查看帮助"
