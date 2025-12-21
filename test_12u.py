#!/usr/bin/env python3
"""12U 测试交易（满足 ETH 最小下单要求）"""
import asyncio
import logging
import sys
import os
import time

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_12u_trade():
    """测试12U交易"""
    account_address = env_vars.get('HYPERLIQUID_ACCOUNT_ADDRESS')
    private_key = env_vars.get('HYPERLIQUID_PRIVATE_KEY')
    use_testnet = env_vars.get('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

    print("=" * 70)
    print("🧪 Hyperliquid 12U 交易测试")
    print("=" * 70)
    print(f"账户: {account_address}")
    print(f"网络: {'Testnet' if use_testnet else 'Mainnet ⚠️'}")
    print()

    base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
    info_client = Info(base_url=base_url)

    # 初始化交易客户端
    try:
        wallet = eth_account.Account.from_key(private_key)
        exchange = Exchange(wallet=wallet, base_url=base_url, account_address=account_address)
        logger.info("✅ 客户端初始化成功")
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
        return

    # 获取 ETH 当前价格
    print("📊 获取 ETH 当前价格...")
    try:
        all_mids = info_client.all_mids()
        eth_price = float(all_mids.get('ETH', 3500))  # 默认3500
        print(f"💰 ETH 当前价格: ${eth_price:.2f}")
        print()
    except Exception as e:
        logger.warning(f"⚠️  获取价格失败，使用默认值: {e}")
        eth_price = 3500

    # 计算 12U 对应的 ETH 数量
    TEST_COIN = "ETH"
    TEST_USD_VALUE = 12  # 12U
    TEST_SIZE = TEST_USD_VALUE / eth_price  # 计算ETH数量
    TEST_LEVERAGE = 1

    # 四舍五入到合适的精度（Hyperliquid通常支持到0.001）
    TEST_SIZE = round(TEST_SIZE, 3)

    print("📋 测试参数:")
    print(f"   币种: {TEST_COIN}")
    print(f"   目标金额: ${TEST_USD_VALUE}")
    print(f"   计算仓位: {TEST_SIZE} ETH (约 ${TEST_SIZE * eth_price:.2f})")
    print(f"   杠杆: {TEST_LEVERAGE}x")
    print()

    # 确认
    print("⚠️  即将执行真实交易！")
    print(f"   操作: 开多仓 {TEST_SIZE} ETH → 等待5秒 → 平仓")
    print()
    print("⏳ 3秒后自动开始（Ctrl+C取消）...")
    try:
        for i in range(3, 0, -1):
            print(f"   {i}...")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n❌ 已取消")
        return

    print()
    print("=" * 70)
    print("开始测试...")
    print("=" * 70)
    print()

    try:
        # 步骤 1: 设置杠杆
        print(f"📊 [1/4] 设置杠杆 {TEST_LEVERAGE}x...")
        try:
            result = exchange.update_leverage(TEST_LEVERAGE, TEST_COIN)
            logger.info(f"✅ 杠杆设置: {result}")
        except Exception as e:
            logger.warning(f"⚠️  杠杆设置: {e}")
        print()

        # 步骤 2: 开多仓
        print(f"📈 [2/4] 市价开多 {TEST_SIZE} {TEST_COIN}...")
        try:
            order_result = exchange.market_open(TEST_COIN, True, TEST_SIZE)
            logger.info(f"✅ 开仓指令已发送")
            print(f"   订单响应: {order_result}")

            # 检查订单状态
            if isinstance(order_result, dict):
                status = order_result.get('status', 'unknown')
                if status == 'ok':
                    print(f"   ✅ 订单状态: 成功")
                    statuses = order_result.get('response', {}).get('data', {}).get('statuses', [])
                    if statuses:
                        for s in statuses:
                            filled = s.get('filled', {})
                            print(f"   成交数量: {filled.get('totalSz', 'N/A')}")
                            print(f"   成交均价: ${filled.get('avgPx', 'N/A')}")
                else:
                    print(f"   ⚠️  订单状态: {status}")
            print()
        except Exception as e:
            logger.error(f"❌ 开仓失败: {e}")
            print(f"   错误详情: {e}")
            print()
            return

        # 等待订单成交
        print("⏳ 等待 3 秒确保订单成交...")
        await asyncio.sleep(3)

        # 步骤 3: 检查仓位
        print("📊 [3/4] 查询持仓...")
        try:
            user_state = info_client.user_state(account_address)
            positions = user_state.get('assetPositions', [])

            found_position = False
            for pos in positions:
                position_data = pos.get('position', {})
                if position_data.get('coin') == TEST_COIN:
                    size = float(position_data.get('szi', 0))
                    if size != 0:
                        found_position = True
                        entry_px = float(position_data.get('entryPx', 0))
                        unrealized_pnl = float(position_data.get('unrealizedPnl', 0))

                        print(f"   ✅ 找到 {TEST_COIN} 仓位:")
                        print(f"      仓位: {size} ETH")
                        print(f"      入场价: ${entry_px:.2f}")
                        print(f"      未实现盈亏: ${unrealized_pnl:.4f}")
                        break

            if not found_position:
                print(f"   ⚠️  未找到 {TEST_COIN} 仓位")
                print(f"   可能原因:")
                print(f"   • 订单被拒绝（余额不足、价格限制等）")
                print(f"   • 订单仍在处理中")
                print(f"   • 仓位太小被系统四舍五入")

        except Exception as e:
            logger.error(f"❌ 查询仓位失败: {e}")
        print()

        # 等待
        print("⏳ 等待 5 秒后平仓...")
        await asyncio.sleep(5)

        # 步骤 4: 平仓
        print(f"📉 [4/4] 市价平仓 {TEST_COIN}...")
        try:
            close_result = exchange.market_close(TEST_COIN)
            logger.info(f"✅ 平仓指令已发送")
            print(f"   平仓响应: {close_result}")

            if isinstance(close_result, dict):
                status = close_result.get('status', 'unknown')
                print(f"   订单状态: {status}")

        except Exception as e:
            logger.error(f"❌ 平仓失败: {e}")
            print(f"   错误: {e}")
        print()

        # 最终检查
        print("⏳ 等待 3 秒...")
        await asyncio.sleep(3)

        print("📊 最终状态检查...")
        try:
            user_state = info_client.user_state(account_address)
            positions = user_state.get('assetPositions', [])

            has_position = False
            for pos in positions:
                position_data = pos.get('position', {})
                if position_data.get('coin') == TEST_COIN:
                    size = float(position_data.get('szi', 0))
                    if size != 0:
                        has_position = True
                        print(f"   ⚠️  仍有仓位: {size} {TEST_COIN}")

            if not has_position:
                print(f"   ✅ {TEST_COIN} 已完全平仓")

        except Exception as e:
            logger.error(f"❌ 最终检查失败: {e}")

        print()
        print("=" * 70)
        print("🎉 测试完成！")
        print("=" * 70)

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_12u_trade())
