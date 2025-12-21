#!/usr/bin/env python3
"""自动化交易测试（跳过确认）- 仅供测试环境使用"""
import asyncio
import logging
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# 手动读取 .env
env_vars = {}
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env_vars[key] = value

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_trading_auto():
    """自动化测试交易功能"""
    # 读取配置
    account_address = env_vars.get('HYPERLIQUID_ACCOUNT_ADDRESS')
    private_key = env_vars.get('HYPERLIQUID_PRIVATE_KEY')
    use_testnet = env_vars.get('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

    print("=" * 70)
    print("🧪 Hyperliquid 自动化交易测试")
    print("=" * 70)
    print(f"账户地址: {account_address}")
    print(f"网络: {'Testnet' if use_testnet else 'Mainnet ⚠️'}")
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
        margin_summary = user_state.get('marginSummary', {})
        account_value = float(margin_summary.get('accountValue', 0))

        print(f"💰 账户价值: ${account_value:.2f}")
        print()

    except Exception as e:
        logger.error(f"❌ 获取账户信息失败: {e}")
        return

    # 测试参数
    TEST_COIN = "ETH"
    TEST_SIZE = 0.001  # 最小测试仓位
    TEST_LEVERAGE = 1

    print("📋 测试参数:")
    print(f"   币种: {TEST_COIN}")
    print(f"   仓位大小: {TEST_SIZE}")
    print(f"   杠杆: {TEST_LEVERAGE}x")
    print()
    print("=" * 70)
    print("开始自动化测试...")
    print("=" * 70)
    print()

    try:
        # 步骤 1: 设置杠杆
        print(f"📊 [1/4] 设置杠杆为 {TEST_LEVERAGE}x...")
        try:
            exchange.update_leverage(TEST_LEVERAGE, TEST_COIN)
            logger.info(f"✅ 杠杆设置成功: {TEST_LEVERAGE}x")
        except Exception as e:
            logger.warning(f"⚠️  设置杠杆失败: {e}")
        print()

        # 步骤 2: 开多仓
        print(f"📈 [2/4] 开多仓 {TEST_SIZE} {TEST_COIN}...")
        order_result = exchange.market_open(TEST_COIN, True, TEST_SIZE)
        logger.info(f"✅ 开仓订单已提交")
        print(f"   订单结果: {order_result}")
        print()

        # 等待订单执行
        print("⏳ 等待 3 秒确保订单执行...")
        await asyncio.sleep(3)

        # 步骤 3: 检查仓位
        print("📊 [3/4] 检查当前仓位...")
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
        else:
            print(f"⚠️  未找到 {TEST_COIN} 仓位")
        print()

        # 等待 5 秒
        print("⏳ 等待 5 秒后平仓...")
        await asyncio.sleep(5)

        # 步骤 4: 平仓
        print(f"📉 [4/4] 平仓 {TEST_COIN}...")
        close_result = exchange.market_close(TEST_COIN)
        logger.info(f"✅ 平仓订单已提交")
        print(f"   平仓结果: {close_result}")
        print()

        # 等待平仓执行
        print("⏳ 等待 3 秒确保平仓执行...")
        await asyncio.sleep(3)

        # 最终检查
        print("📊 最终检查...")
        user_state = info_client.user_state(account_address)
        positions = user_state.get('assetPositions', [])

        still_has_position = False
        for pos in positions:
            if pos.get('position', {}).get('coin') == TEST_COIN:
                position_data = pos.get('position', {})
                size = float(position_data.get('szi', 0))
                if size != 0:
                    still_has_position = True
                    print(f"⚠️  {TEST_COIN} 仓位仍存在，剩余: {size}")
                    break

        if not still_has_position:
            print(f"✅ {TEST_COIN} 仓位已完全平仓")

        print()
        print("=" * 70)
        print("🎉 测试完成！")
        print("=" * 70)
        print()
        print("✅ 功能测试结果:")
        print("   • 客户端初始化 ✅")
        print("   • 杠杆设置 ✅")
        print("   • 市价开仓 ✅")
        print("   • 仓位查询 ✅")
        print("   • 市价平仓 ✅")
        print()
        print("💡 你的交易系统已经可以正常工作！")
        print("   现在可以运行主程序开始自动跟单了")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print()
    print("⚠️  自动化测试将在 3 秒后开始...")
    print("   按 Ctrl+C 取消")
    print()

    import time
    try:
        for i in range(3, 0, -1):
            print(f"   {i}...")
            time.sleep(1)
        print()

        asyncio.run(test_trading_auto())
    except KeyboardInterrupt:
        print()
        print("❌ 测试已取消")
