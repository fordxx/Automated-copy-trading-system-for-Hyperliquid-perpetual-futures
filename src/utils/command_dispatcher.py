"""多实例命令分发器。

负责处理 Telegram 命令并分发给对应的实例。
"""
import logging
from typing import Dict, List, Optional, Callable
import asyncio

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """命令分发器。
    
    处理来自 Telegram 的命令，并将其路由到指定的实例或全部实例。
    """
    
    def __init__(self):
        """初始化命令分发器。"""
        self.command_handlers: Dict[str, Callable] = {}
        self.instances: Dict[str, Dict] = {}  # instance_name -> instance_info
    
    def register_instance(self, instance_name: str, instance_info: Dict):
        """注册一个实例。
        
        Args:
            instance_name: 实例名称
            instance_info: 实例信息（包含 wallet_label, account_address 等）
        """
        self.instances[instance_name] = instance_info
        logger.debug(f"✅ Registered instance: {instance_name}")
    
    def register_handler(self, command: str, handler: Callable):
        """注册命令处理器。
        
        Args:
            command: 命令名称（不含 /）
            handler: 异步处理函数，签名: async def handler(command, args, target_wallets) -> str
        """
        self.command_handlers[command] = handler
        logger.debug(f"✅ Registered handler for command: {command}")
    
    async def dispatch(self, command: str, args: str) -> str:
        """分发命令。
        
        Args:
            command: 命令名称
            args: 命令参数（可以包含目标钱包名）
            
        Returns:
            命令响应文本
        """
        # 解析目标钱包
        target_wallets = self._parse_targets(args)
        
        # 如果有注册的处理器，使用它
        if command in self.command_handlers:
            handler = self.command_handlers[command]
            return await handler(command, args, target_wallets, self.instances)
        
        # 默认处理
        return self._default_handler(command, args, target_wallets)
    
    def _parse_targets(self, args: str) -> List[str]:
        """解析目标钱包列表。
        
        Args:
            args: 命令参数
            
        Returns:
            目标钱包名称列表
        """
        args = args.strip()
        if not args or args.lower() == "all":
            # 所有实例
            return list(self.instances.keys())
        else:
            # 指定的实例
            wallet_name = args.split()[0]  # 取第一个参数
            if wallet_name in self.instances:
                return [wallet_name]
            else:
                # 如果不存在，返回所有实例
                logger.warning(f"Unknown wallet: {wallet_name}, targeting all instances")
                return list(self.instances.keys())
    
    def _default_handler(self, command: str, args: str, target_wallets: List[str]) -> str:
        """默认命令处理器。"""
        target_info = "全部钱包" if len(target_wallets) == len(self.instances) else f"钱包: {', '.join(target_wallets)}"
        
        if command == "help":
            return (
                "🤖 *Hyperliquid Copy Trader 帮助*\n\n"
                "*可用命令：*\n"
                "• /help - 显示此帮助信息\n"
                "• /status [钱包] - 查看状态\n"
                "• /wallets - 列出所有钱包\n"
                "• /pause [钱包] - 暂停跟单\n"
                "• /resume [钱包] - 恢复跟单\n"
                "• /pnl [钱包] - 显示盈亏\n"
                "• /positions [钱包] - 显示持仓\n\n"
                "*使用示例：*\n"
                "• /pause - 暂停全部钱包\n"
                "• /pause wallet_1 - 仅暂停wallet_1"
            )
        elif command == "wallets":
            wallets_list = "\n".join([
                f"• {name} ({info.get('wallet_label', info.get('account_address', 'Unknown'))[:20]})"
                for name, info in self.instances.items()
            ])
            return f"👛 *所有钱包实例：*\n{wallets_list}"
        elif command == "status":
            status_list = "\n".join([
                f"• {name}: 🟢 运行中"
                for name in target_wallets
            ])
            return f"📊 *状态报告 ({target_info}):*\n{status_list}"
        elif command == "pause":
            return f"⏸️ *已暂停 ({target_info})*"
        elif command == "resume":
            return f"▶️ *已恢复 ({target_info})*"
        elif command == "pnl":
            return f"💰 *盈亏数据 ({target_info}):*\n获取中..."
        elif command == "positions":
            return f"📋 *持仓数据 ({target_info}):*\n获取中..."
        else:
            return f"❓ 未知命令：/{command}\n输入 /help 查看帮助"
