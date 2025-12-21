#!/usr/bin/env python3
"""测试WebSocket实时监控功能"""
import asyncio
import logging
import sys
import os
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dotenv import load_dotenv
from src.websocket_monitor import WebSocketMonitor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 手动读取 .env
load_dotenv()

async def test_callback(trade):
    """测试回调函数"""
    logger.info(f"🎯 [CALLBACK] Received trade: {trade.coin} {trade.action} {trade.size} @ ${trade.price:.2f}")


async def main():
    """主测试函数"""
    target_address = os.getenv('TARGET_ADDRESS')
    exclude_addresses_str = os.getenv('EXCLUDE_ADDRESSES', '')
    exclude_addresses = [addr.strip() for addr in exclude_addresses_str.split(',') if addr.strip()]
    use_testnet = os.getenv('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

    print("=" * 70)
    print("🧪 WebSocket 实时监控测试")
    print("=" * 70)
    print(f"目标地址: {target_address}")
    print(f"排除地址: {exclude_addresses}")
    print(f"网络: {'Testnet' if use_testnet else 'Mainnet'}")
    print()
    print("⚡ WebSocket模式: 实时推送，<1秒响应")
    print("📡 等待目标地址的交易信号...")
    print()
    print("按 Ctrl+C 停止监控")
    print("=" * 70)
    print()

    # 创建WebSocket监控器
    monitor = WebSocketMonitor(
        target_address=target_address,
        use_testnet=use_testnet,
        exclude_addresses=exclude_addresses,
        on_trade_callback=test_callback
    )

    try:
        # 启动监控
        await monitor.start()

    except KeyboardInterrupt:
        print()
        logger.info("⏹️  收到停止信号，正在关闭...")
        await monitor.stop()

        # 显示统计信息
        stats = monitor.get_stats()
        print()
        print("=" * 70)
        print("📊 监控统计")
        print("=" * 70)
        print(f"总消息数: {stats['total_messages']}")
        print(f"快照消息: {stats['snapshot_messages']}")
        print(f"实时消息: {stats['streaming_messages']}")
        print(f"检测到的交易: {stats['trades_detected']}")
        if stats['last_trade_time']:
            print(f"最后交易时间: {stats['last_trade_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"已处理交易哈希数: {stats['processed_tx_count']}")
        print("=" * 70)

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print()
    print("⏳ 测试即将开始...")
    print()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print("❌ 测试已取消")
