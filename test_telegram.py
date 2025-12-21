#!/usr/bin/env python3
"""测试 Telegram 机器人配置"""
import os
import asyncio
from dotenv import load_dotenv
import aiohttp

async def test_telegram_bot():
    """测试 Telegram 机器人"""
    load_dotenv()

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    print("=" * 60)
    print("📱 Telegram 机器人测试")
    print("=" * 60)
    print(f"Bot Token: {bot_token[:20]}...{bot_token[-10:] if len(bot_token) > 30 else bot_token}")
    print(f"Chat ID: {chat_id}")
    print()

    if not bot_token or not chat_id:
        print("❌ 错误：TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未设置")
        return False

    # 测试发送消息
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    test_message = """🤖 Telegram 机器人测试成功！

✅ 连接正常
📡 通知系统已就绪
🚀 Hyperliquid Copy Trader 准备启动

你将收到以下类型的通知：
• 程序启动/停止
• 交易检测和执行
• 仓位状态更新
• 风险警报

测试完成！"""

    try:
        async with aiohttp.ClientSession() as session:
            data = {
                "chat_id": chat_id,
                "text": test_message,
                "parse_mode": "HTML"
            }

            print("📤 发送测试消息...")
            async with session.post(url, json=data) as response:
                result = await response.json()

                if result.get('ok'):
                    print("✅ 测试消息发送成功！")
                    print(f"   Message ID: {result['result']['message_id']}")
                    print()
                    print("🎉 请检查你的 Telegram 查看测试消息")
                    return True
                else:
                    print(f"❌ 发送失败：{result.get('description', 'Unknown error')}")
                    if result.get('error_code') == 400:
                        print("   可能的原因：Chat ID 不正确或机器人未被启动")
                        print("   请确保：")
                        print("   1. 在 Telegram 中搜索你的机器人")
                        print("   2. 点击 START 按钮")
                        print("   3. Chat ID 正确")
                    elif result.get('error_code') == 401:
                        print("   可能的原因：Bot Token 不正确")
                        print("   请检查 TELEGRAM_BOT_TOKEN 是否正确")
                    return False

    except Exception as e:
        print(f"❌ 连接失败：{e}")
        print("   请检查网络连接")
        return False

if __name__ == "__main__":
    asyncio.run(test_telegram_bot())
