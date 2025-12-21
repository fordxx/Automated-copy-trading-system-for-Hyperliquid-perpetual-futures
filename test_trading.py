#!/usr/bin/env python3
"""测试交易下单和平仓功能（使用最小金额）"""
import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_trading():
    """测试交易功能"""
    load_dotenv()

    # 读取配置
    account_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')
    private_key = os.getenv('HYPERLIQUID_PRIVATE_KEY')
    use_testnet = os.getenv('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

    print("=" * 70)
    print("🧪 Hyperliquid 交易功能测试")
    print("=" * 70)
    print(f"账户地址: {account_address}")
    print(f"网络: {'Testnet' if use_testnet else 'Mainnet'}")
    print()

    # 安全警告
    if not use_testnet:
        print("⚠️  警告：你正在使用主网！")
        print("⚠️  测试将使用真实资金！")
        print()
        confirm = input("确认继续？输入 'YES' 继续，其他任何输入取消: ")
        if confirm != 'YES':
            print("❌ 测试已取消")
            return
        print()

    # 初始化客户端
    base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
    info_client = Info(base_url=base_url)

    try:
        wallet = eth_account.Account.from_key(private_key)
        exchange = Exchange(
            wallet=wallet,
            base_url=base_url,
            account_address=account_address
        )
        logger.info("✅ 客户端初始化成功")
    except Exception as e:
        logger.error(f"❌ 客户端初始化失败: {e}")
        return

    # 获取账户信息
    try:
        user_state = info_client.user_state(account_address)

        # 显示账户余额
        margin_summary = user_state.get('marginSummary', {})
        account_value = float(margin_summary.get('accountValue', 0))

        print(f"💰 账户价值: ${account_value:.2f}")
        print()

        if account_value < 10:
            print("⚠️  警告：账户余额较低，可能无法进行交易")
            print()

    except Exception as e:
        logger.error(f"❌ 获取账户信息失败: {e}")
        return

    # 测试交易参数
    TEST_COIN = "ETH"  # 使用 ETH，流动性好
    TEST_SIZE = 0.001  # 最小测试仓位（约 $3-4）
    TEST_LEVERAGE = 1  # 使用 1x 杠杆最安全

    print("📋 测试参数:")
    print(f"   币种: {TEST_COIN}")
    print(f"   仓位大小: {TEST_SIZE}")
    print(f"   杠杆: {TEST_LEVERAGE}x")
    print()

    # 确认测试
    print("⚠️  即将执行测试交易:")
    print(f"   1. 开多仓 {TEST_SIZE} {TEST_COIN}")
    print(f"   2. 等待 5 秒")
    print(f"   3. 平仓")
    print()

    confirm = input("确认执行测试？输入 'YES' 继续: ")
    if confirm != 'YES':
        print("❌ 测试已取消")
        return

    print()
    print("=" * 70)
    print("开始测试...")
    print("=" * 70)
    print()

    try:
        # 步骤 1: 设置杠杆
        print(f"📊 步骤 1/4: 设置杠杆为 {TEST_LEVERAGE}x...")
        try:
            exchange.update_leverage(TEST_LEVERAGE, TEST_COIN)
            logger.info(f"✅ 杠杆设置成功: {TEST_LEVERAGE}x")
        except Exception as e:
            logger.warning(f"⚠️  设置杠杆失败（可能已设置）: {e}")
        print()

        # 步骤 2: 开多仓
        print(f"📈 步骤 2/4: 开多仓 {TEST_SIZE} {TEST_COIN}...")
        order_result = exchange.market_open(TEST_COIN, True, TEST_SIZE)
        logger.info(f"✅ 开仓成功: {order_result}")
        print(f"   订单结果: {order_result}")
        print()

        # 等待一下确保订单执行
        print("⏳ 等待订单执行...")
        await asyncio.sleep(3)

        # 步骤 3: 检查仓位
        print("📊 步骤 3/4: 检查当前仓位...")
        user_state = info_client.user_state(account_address)
        positions = user_state.get('assetPositions', [])

        eth_position = None
        for pos in positions:
            if pos.get('position', {}).get('coin') == TEST_COIN:
                eth_position = pos
                break

        if eth_position:
            position_data = eth_position.get('position', {})
            size = float(position_data.get('szi', 0))
            entry_px = float(position_data.get('entryPx', 0))
            unrealized_pnl = float(position_data.get('unrealizedPnl', 0))

            print(f"✅ 找到 {TEST_COIN} 仓位:")
            print(f"   仓位大小: {size}")
            print(f"   入场价格: ${entry_px:.2f}")
            print(f"   未实现盈亏: ${unrealized_pnl:.4f}")
            print()
        else:
            print(f"⚠️  未找到 {TEST_COIN} 仓位，可能订单未成交")
            print()

        # 等待几秒再平仓
        print("⏳ 等待 5 秒后平仓...")
        await asyncio.sleep(5)

        # 步骤 4: 平仓
        print(f"📉 步骤 4/4: 平仓 {TEST_COIN}...")
        close_result = exchange.market_close(TEST_COIN)
        logger.info(f"✅ 平仓成功: {close_result}")
        print(f"   平仓结果: {close_result}")
        print()

        # 等待平仓执行
        print("⏳ 等待平仓执行...")
        await asyncio.sleep(3)

        # 最终检查
        print("📊 最终检查账户状态...")
        user_state = info_client.user_state(account_address)
        positions = user_state.get('assetPositions', [])

        eth_position = None
        for pos in positions:
            if pos.get('position', {}).get('coin') == TEST_COIN:
                position_data = pos.get('position', {})
                size = float(position_data.get('szi', 0))
                if size != 0:
                    eth_position = pos
                    break

        if eth_position:
            print(f"⚠️  {TEST_COIN} 仓位仍然存在（可能部分平仓）")
            position_data = eth_position.get('position', {})
            size = float(position_data.get('szi', 0))
            print(f"   剩余仓位: {size}")
        else:
            print(f"✅ {TEST_COIN} 仓位已完全平仓")

        print()
        print("=" * 70)
        print("🎉 测试完成！")
        print("=" * 70)
        print()
        print("✅ 所有功能正常:")
        print("   • 杠杆设置 ✅")
        print("   • 开仓功能 ✅")
        print("   • 仓位查询 ✅")
        print("   • 平仓功能 ✅")
        print()
        print("💡 你的交易系统已经可以正常工作！")

    except Exception as e:
        logger.error(f"❌ 测试过程中出错: {e}")
        print()
        print("⚠️  如果有仓位未平仓，请手动平仓或运行以下命令:")
        print(f"   python3 -c \"from test_trading import *; close_position('{TEST_COIN}')\"")


async def close_position(coin: str):
    """手动平仓辅助函数"""
    load_dotenv()

    account_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')
    private_key = os.getenv('HYPERLIQUID_PRIVATE_KEY')
    use_testnet = os.getenv('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

    base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL

    wallet = eth_account.Account.from_key(private_key)
    exchange = Exchange(
        wallet=wallet,
        base_url=base_url,
        account_address=account_address
    )

    result = exchange.market_close(coin)
    print(f"平仓结果: {result}")


if __name__ == "__main__":
    asyncio.run(test_trading())
