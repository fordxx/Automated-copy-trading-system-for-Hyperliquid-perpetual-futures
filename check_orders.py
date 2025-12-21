#!/usr/bin/env python3
"""检查订单和仓位状态"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import eth_account
from hyperliquid.info import Info
from hyperliquid.utils import constants

# 手动读取 .env
env_vars = {}
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env_vars[key] = value

account_address = env_vars.get('HYPERLIQUID_ACCOUNT_ADDRESS')
use_testnet = env_vars.get('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
info_client = Info(base_url=base_url)

print("=" * 70)
print("📊 账户状态检查")
print("=" * 70)
print(f"账户地址: {account_address}")
print(f"网络: {'Testnet' if use_testnet else 'Mainnet'}")
print()

# 1. 检查账户状态
print("1️⃣ 账户概览")
print("-" * 70)
try:
    user_state = info_client.user_state(account_address)

    # 账户余额
    margin_summary = user_state.get('marginSummary', {})
    account_value = float(margin_summary.get('accountValue', 0))
    total_margin_used = float(margin_summary.get('totalMarginUsed', 0))
    total_ntl_pos = float(margin_summary.get('totalNtlPos', 0))
    total_raw_usd = float(margin_summary.get('totalRawUsd', 0))

    print(f"💰 账户价值: ${account_value:,.2f}")
    print(f"📊 已用保证金: ${total_margin_used:,.2f}")
    print(f"📈 持仓价值: ${total_ntl_pos:,.2f}")
    print(f"💵 可用余额: ${total_raw_usd:,.2f}")
    print()

except Exception as e:
    print(f"❌ 获取账户状态失败: {e}")
    print()

# 2. 检查当前持仓
print("2️⃣ 当前持仓")
print("-" * 70)
try:
    user_state = info_client.user_state(account_address)
    positions = user_state.get('assetPositions', [])

    if not positions:
        print("📭 当前无持仓")
    else:
        print(f"📦 共 {len(positions)} 个持仓:\n")
        for i, pos in enumerate(positions, 1):
            position_data = pos.get('position', {})
            coin = position_data.get('coin', 'Unknown')
            size = float(position_data.get('szi', 0))

            # 跳过零仓位
            if size == 0:
                continue

            entry_px = float(position_data.get('entryPx', 0))
            leverage = position_data.get('leverage', {}).get('value', 1)
            unrealized_pnl = float(position_data.get('unrealizedPnl', 0))
            liquidation_px = float(position_data.get('liquidationPx', 0))

            direction = "做多 📈" if size > 0 else "做空 📉"
            pnl_symbol = "🟢" if unrealized_pnl >= 0 else "🔴"

            print(f"   [{i}] {coin} {direction}")
            print(f"       仓位大小: {abs(size)}")
            print(f"       入场价格: ${entry_px:,.2f}")
            print(f"       杠杆: {leverage}x")
            print(f"       {pnl_symbol} 未实现盈亏: ${unrealized_pnl:,.4f}")
            print(f"       清算价格: ${liquidation_px:,.2f}")
            print()

except Exception as e:
    print(f"❌ 获取持仓失败: {e}")
print()

# 3. 检查最近成交（订单历史）
print("3️⃣ 最近成交记录（最新10条）")
print("-" * 70)
try:
    fills = info_client.user_fills(account_address)

    if not fills:
        print("📭 暂无成交记录")
    else:
        print(f"📜 共找到 {len(fills)} 条成交记录\n")

        # 只显示最近10条
        for i, fill in enumerate(fills[:10], 1):
            coin = fill.get('coin', 'Unknown')
            side = fill.get('side', 'Unknown')
            size = float(fill.get('sz', 0))
            price = float(fill.get('px', 0))
            timestamp = fill.get('time', 0)

            # 转换时间戳
            from datetime import datetime
            dt = datetime.fromtimestamp(timestamp / 1000)
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')

            side_text = "买入 🟢" if side == "B" else "卖出 🔴"

            print(f"   [{i}] {time_str}")
            print(f"       {coin} {side_text}")
            print(f"       数量: {size}")
            print(f"       价格: ${price:,.2f}")
            print()

except Exception as e:
    print(f"❌ 获取成交记录失败: {e}")
print()

print("=" * 70)
print("✅ 检查完成")
print("=" * 70)
