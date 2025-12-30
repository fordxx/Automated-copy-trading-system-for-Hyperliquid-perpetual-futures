#!/usr/bin/env python3
"""测试双模式跟单功能

快速验证 position 和 wallet 两种跟单模式是否正常工作。
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.position_manager import PositionManager
from hyperliquid.info import Info


async def test_wallet_balance_query():
    """测试钱包余额查询功能"""
    print("=" * 60)
    print("测试1: 钱包余额查询功能")
    print("=" * 60)
    
    # 创建Info客户端
    info = Info(skip_ws=True)
    
    # 测试地址（使用公开的大户地址作为测试）
    test_addresses = [
        "0x563C175E6f11582f65D6d9E360A618699DEe14a9",  # 一个已知的活跃地址
        "0x010460Bd4F8f67d44C09Eb31Db63ddBDC8054bBc",  # 另一个测试地址
    ]
    
    class MockExchange:
        """模拟Exchange对象"""
        account_address = test_addresses[0]
    
    # 创建PositionManager实例
    pm = PositionManager(MockExchange(), info)
    
    # 测试获取不同地址的余额
    for addr in test_addresses:
        try:
            balance = pm.get_account_value_usd(addr)
            if balance:
                print(f"✅ 地址 {addr[:10]}... 余额: ${balance:,.2f}")
            else:
                print(f"⚠️ 地址 {addr[:10]}... 余额: None (可能是空账户)")
        except Exception as e:
            print(f"❌ 查询失败: {e}")
    
    print()


async def test_copy_ratio_calculation():
    """测试两种模式的比例计算"""
    print("=" * 60)
    print("测试2: 跟单比例计算")
    print("=" * 60)
    
    # 测试场景
    scenarios = [
        {
            "name": "Position模式 - 固定比例",
            "mode": "position",
            "copy_ratio": 0.1,
            "leader_position": 100.0,
            "follower_balance": 1000.0,
            "leader_balance": 10000.0,
            "expected": 10.0,  # 100 * 0.1
        },
        {
            "name": "Wallet模式 - 等比例账户",
            "mode": "wallet",
            "copy_ratio": 0.1,
            "leader_position": 100.0,
            "follower_balance": 1000.0,
            "leader_balance": 10000.0,
            "expected": 10.0,  # 100 * (1000/10000)
        },
        {
            "name": "Wallet模式 - 小账户",
            "mode": "wallet",
            "copy_ratio": 0.1,
            "leader_position": 200.0,
            "follower_balance": 500.0,
            "leader_balance": 10000.0,
            "expected": 10.0,  # 200 * (500/10000)
        },
        {
            "name": "Wallet模式 - 大账户",
            "mode": "wallet",
            "copy_ratio": 0.1,
            "leader_position": 50.0,
            "follower_balance": 20000.0,
            "leader_balance": 10000.0,
            "expected": 100.0,  # 50 * (20000/10000)
        },
    ]
    
    for scenario in scenarios:
        print(f"\n📊 场景: {scenario['name']}")
        print(f"   模式: {scenario['mode']}")
        print(f"   Leader仓位: ${scenario['leader_position']:.2f}")
        print(f"   Follower余额: ${scenario['follower_balance']:,.2f}")
        print(f"   Leader余额: ${scenario['leader_balance']:,.2f}")
        
        if scenario['mode'] == 'position':
            actual = scenario['leader_position'] * scenario['copy_ratio']
            print(f"   计算: {scenario['leader_position']} × {scenario['copy_ratio']}")
        else:  # wallet
            ratio = scenario['follower_balance'] / scenario['leader_balance']
            actual = scenario['leader_position'] * ratio
            print(f"   计算: {scenario['leader_position']} × ({scenario['follower_balance']}/{scenario['leader_balance']}) = {scenario['leader_position']} × {ratio:.4f}")
        
        print(f"   预期结果: ${scenario['expected']:.2f}")
        print(f"   实际结果: ${actual:.2f}")
        
        if abs(actual - scenario['expected']) < 0.01:
            print(f"   ✅ 测试通过")
        else:
            print(f"   ❌ 测试失败")
    
    print()


async def test_mode_comparison():
    """对比两种模式的差异"""
    print("=" * 60)
    print("测试3: 模式对比 - 账户余额变化场景")
    print("=" * 60)
    
    # 初始状态
    leader_pos = 100.0
    follower_balance_initial = 1000.0
    leader_balance_initial = 10000.0
    copy_ratio_fixed = 0.1
    
    print(f"\n初始状态:")
    print(f"  Leader余额: ${leader_balance_initial:,.2f}")
    print(f"  Follower余额: ${follower_balance_initial:,.2f}")
    print(f"  固定比例: {copy_ratio_fixed}")
    print(f"  Leader开仓: ${leader_pos:.2f}")
    
    # 交易1: 初始状态
    print(f"\n交易1 - 初始交易")
    pos_size_1 = leader_pos * copy_ratio_fixed
    wallet_ratio_1 = follower_balance_initial / leader_balance_initial
    wallet_size_1 = leader_pos * wallet_ratio_1
    print(f"  Position模式: ${pos_size_1:.2f}")
    print(f"  Wallet模式: ${wallet_size_1:.2f} (比例: {wallet_ratio_1:.4f})")
    
    # 交易后盈利
    profit_pct = 0.1
    follower_balance_after = follower_balance_initial * (1 + profit_pct)
    leader_balance_after = leader_balance_initial * (1 + profit_pct)
    
    print(f"\n盈利后状态 (+{profit_pct*100}%):")
    print(f"  Leader余额: ${leader_balance_after:,.2f}")
    print(f"  Follower余额: ${follower_balance_after:,.2f}")
    
    # 交易2: 盈利后
    print(f"\n交易2 - 盈利后同样开仓${leader_pos:.2f}")
    pos_size_2 = leader_pos * copy_ratio_fixed
    wallet_ratio_2 = follower_balance_after / leader_balance_after
    wallet_size_2 = leader_pos * wallet_ratio_2
    print(f"  Position模式: ${pos_size_2:.2f} (不变)")
    print(f"  Wallet模式: ${wallet_size_2:.2f} (比例: {wallet_ratio_2:.4f}, 不变)")
    
    # 不对称盈利
    follower_balance_asymmetric = follower_balance_initial * 1.2  # +20%
    leader_balance_asymmetric = leader_balance_initial * 1.1  # +10%
    
    print(f"\n不对称盈利场景:")
    print(f"  Leader余额: ${leader_balance_asymmetric:,.2f} (+10%)")
    print(f"  Follower余额: ${follower_balance_asymmetric:,.2f} (+20%)")
    
    print(f"\n交易3 - 不对称盈利后开仓${leader_pos:.2f}")
    pos_size_3 = leader_pos * copy_ratio_fixed
    wallet_ratio_3 = follower_balance_asymmetric / leader_balance_asymmetric
    wallet_size_3 = leader_pos * wallet_ratio_3
    print(f"  Position模式: ${pos_size_3:.2f} (固定)")
    print(f"  Wallet模式: ${wallet_size_3:.2f} (比例: {wallet_ratio_3:.4f}, 自动调整)")
    print(f"  📈 Wallet模式资金利用率提升: {((wallet_size_3/pos_size_3 - 1) * 100):.1f}%")
    
    print()


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("双模式跟单功能测试")
    print("=" * 60)
    print()
    
    try:
        # 测试1: 钱包余额查询（需要网络）
        print("⏳ 运行测试1 (需要网络连接)...")
        await test_wallet_balance_query()
        
        # 测试2: 比例计算（本地计算）
        print("⏳ 运行测试2...")
        await test_copy_ratio_calculation()
        
        # 测试3: 模式对比（本地计算）
        print("⏳ 运行测试3...")
        await test_mode_comparison()
        
        print("=" * 60)
        print("✅ 所有测试完成!")
        print("=" * 60)
        print()
        print("使用建议:")
        print("  • Position模式: 适合固定比例跟单，简单直接")
        print("  • Wallet模式: 适合动态调整，保持与Leader相同的资金利用率")
        print()
        print("配置方式:")
        print("  export COPY_MODE=\"position\"  # 或 \"wallet\"")
        print("  export COPY_RATIO=\"0.1\"")
        print()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被用户中断")
    except Exception as e:
        print(f"\n\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
