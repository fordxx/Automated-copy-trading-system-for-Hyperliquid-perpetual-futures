#!/usr/bin/env python3
"""Test Telegram notifications for Hyperliquid Copy Trader."""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.notifications.telegram import TelegramNotifier


async def test_telegram_notifications():
    """测试Telegram通知功能。"""
    if len(sys.argv) != 3:
        print("用法: python test_telegram.py <bot_token> <chat_id>")
        print("例如: python test_telegram.py 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 123456789")
        sys.exit(1)

    bot_token = sys.argv[1]
    chat_id = sys.argv[2]

    print("🧪 测试Telegram通知功能")
    print(f"Bot Token: {bot_token[:10]}...")
    print(f"Chat ID: {chat_id}")
    print()

    # 创建通知器
    notifier = TelegramNotifier(bot_token, chat_id)

    try:
        # 初始化
        await notifier.initialize()
        print("✅ Telegram通知器初始化成功")

        # 测试启动通知
        print("📤 发送启动通知...")
        await notifier.send_startup_notification()
        print("✅ 启动通知发送成功")

        # 等待一下
        await asyncio.sleep(2)

        # 测试交易通知
        print("📤 发送交易通知...")
        trade_data = {
            'action': 'open_long',
            'coin': 'BTC',
            'size': 0.001,
            'price': 50000.0,
            'leverage': 5
        }
        await notifier.send_trade_notification(trade_data)
        print("✅ 交易通知发送成功")

        # 等待一下
        await asyncio.sleep(2)

        # 测试状态通知
        print("📤 发送状态通知...")
        status_data = {
            'total_positions': 2,
            'total_pnl': 25.50,
            'positions': [
                {
                    'coin': 'BTC',
                    'size': 0.001,
                    'entry_price': 50000.0,
                    'leverage': 5,
                    'pnl': 15.25,
                    'direction': 'long'
                },
                {
                    'coin': 'ETH',
                    'size': -0.01,
                    'entry_price': 3000.0,
                    'leverage': 3,
                    'pnl': 10.25,
                    'direction': 'short'
                }
            ]
        }
        await notifier.send_status_notification(status_data)
        print("✅ 状态通知发送成功")

        # 等待一下
        await asyncio.sleep(2)

        # 测试警报通知
        print("📤 发送警报通知...")
        await notifier.send_alert_notification("warning", "测试警告消息\n这是一条测试警报")
        print("✅ 警报通知发送成功")

        # 等待一下
        await asyncio.sleep(2)

        # 测试关闭通知
        print("📤 发送关闭通知...")
        await notifier.send_shutdown_notification()
        print("✅ 关闭通知发送成功")

        print()
        print("🎉 所有Telegram通知测试完成！")
        print("请检查你的Telegram聊天中是否收到了所有通知消息。")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

    finally:
        # 关闭连接
        await notifier.close()

    return True


if __name__ == "__main__":
    success = asyncio.run(test_telegram_notifications())
    sys.exit(0 if success else 1)