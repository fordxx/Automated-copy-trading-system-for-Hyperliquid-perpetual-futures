#!/usr/bin/env python3
"""快速交易测试 - 无等待"""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# 读取配置
env_vars = {}
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env_vars[key] = value

async def fast_test(coin: str, size: float):
    """快速测试"""
    account_address = env_vars.get('HYPERLIQUID_ACCOUNT_ADDRESS')
    private_key = env_vars.get('HYPERLIQUID_PRIVATE_KEY')
    use_testnet = env_vars.get('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

    base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
    info_client = Info(base_url=base_url)
    wallet = eth_account.Account.from_key(private_key)
    exchange = Exchange(wallet=wallet, base_url=base_url, account_address=account_address)

    print(f"🧪 快速测试 {coin}")
    print("=" * 50)

    # 1. 设置杠杆
    print(f"⚡ [1/4] 设置杠杆 1x...")
    try:
        exchange.update_leverage(1, coin)
        print("   ✅ 完成")
    except Exception as e:
        print(f"   ⚠️  {e}")

    # 2. 开多仓
    print(f"⚡ [2/4] 开多 {size} {coin}...")
    try:
        result = exchange.market_open(coin, True, size)
        if result and result.get('status') == 'ok':
            filled = result.get('response', {}).get('data', {}).get('statuses', [{}])[0].get('filled', {})
            print(f"   ✅ 成交: {filled.get('totalSz')} @ ${filled.get('avgPx')}")
        else:
            print(f"   ⚠️  {result}")
    except Exception as e:
        print(f"   ❌ {e}")
        return

    await asyncio.sleep(0.5)  # 只等0.5秒

    # 3. 查询仓位
    print(f"⚡ [3/4] 查询仓位...")
    try:
        user_state = info_client.user_state(account_address)
        positions = user_state.get('assetPositions', [])
        found = False
        for pos in positions:
            if pos.get('position', {}).get('coin') == coin:
                pdata = pos.get('position', {})
                sz = float(pdata.get('szi', 0))
                if sz != 0:
                    print(f"   ✅ 仓位: {sz} {coin} @ ${pdata.get('entryPx')}")
                    found = True
                    break
        if not found:
            print(f"   ⚠️  未找到仓位")
    except Exception as e:
        print(f"   ❌ {e}")

    await asyncio.sleep(0.5)  # 只等0.5秒

    # 4. 平仓
    print(f"⚡ [4/4] 平仓 {coin}...")
    try:
        result = exchange.market_close(coin)
        if result and result.get('status') == 'ok':
            print(f"   ✅ 平仓成功")
        else:
            print(f"   ⚠️  {result}")
    except Exception as e:
        print(f"   ❌ {e}")

    await asyncio.sleep(0.5)

    # 最终检查
    print(f"⚡ 最终检查...")
    try:
        user_state = info_client.user_state(account_address)
        positions = user_state.get('assetPositions', [])
        for pos in positions:
            if pos.get('position', {}).get('coin') == coin:
                sz = float(pos.get('position', {}).get('szi', 0))
                if sz != 0:
                    print(f"   ⚠️  仍有仓位: {sz}")
                    return
        print(f"   ✅ 完全平仓")
    except:
        pass

    print("=" * 50)
    print("✅ 测试完成！")

if __name__ == "__main__":
    import sys
    coin = sys.argv[1] if len(sys.argv) > 1 else "MELANIA"
    size = float(sys.argv[2]) if len(sys.argv) > 2 else 100

    print(f"\n测试参数: {coin} / 数量: {size}")
    print("启动中...\n")

    asyncio.run(fast_test(coin, size))
