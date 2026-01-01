#!/usr/bin/env python3
"""分析仓位修复方案（Leader vs Follower 当前仓位差异）。"""

import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

def _reexec_in_venv() -> None:
    """If run outside venv, re-exec with repo .venv when available."""
    try:
        in_venv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix
    except Exception:
        in_venv = False
    if in_venv:
        return
    vpy = repo_root / ".venv" / "bin" / "python"
    if vpy.exists() and os.access(vpy, os.X_OK):
        os.execv(str(vpy), [str(vpy), *sys.argv])

_reexec_in_venv()

from hyperliquid.info import Info
from hyperliquid.utils import constants
import yaml
from dotenv import load_dotenv

# Load environment
load_dotenv(dotenv_path=repo_root / ".env", override=False)

config_path = repo_root / "config" / "config.yaml"
if config_path.exists():
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
else:
    config = {}

info = Info(constants.MAINNET_API_URL, skip_ws=True)

follower_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')
leader_address = os.getenv('TARGET_ADDRESS')

# Get positions
follower_state = info.user_state(follower_address)
follower_positions = {pos['position']['coin']: float(pos['position']['szi']) 
                      for pos in follower_state.get('assetPositions', [])}

leader_state = info.user_state(leader_address)
leader_positions = {pos['position']['coin']: float(pos['position']['szi']) 
                    for pos in leader_state.get('assetPositions', [])}

# Get current prices
all_mids = info.all_mids()

try:
    copy_ratio = float(os.getenv("COPY_RATIO", "0.2"))
except Exception:
    copy_ratio = 0.2

print("🔧 仓位修复方案分析")
print("=" * 80)
print()
print(f"Follower: {follower_address} (positions={len(follower_positions)})")
print(f"Leader:   {leader_address} (positions={len(leader_positions)})")
print(f"COPY_RATIO: {copy_ratio:.4f} ({copy_ratio * 100:.2f}%)")
print()

# 方案1：计算需要补充的仓位
ratio_pct = copy_ratio * 100.0
print(f"方案1：【自动补单】计算并自动调整所有仓位到 {ratio_pct:.2f}%")
print("-" * 80)

need_adjustment = []
total_notional = 0
follower_only = []

for coin in sorted(set(leader_positions.keys()) | set(follower_positions.keys())):
    leader_size = leader_positions.get(coin, 0)
    follower_size = follower_positions.get(coin, 0)
    
    if leader_size == 0:
        if follower_size != 0:
            follower_only.append({"coin": coin, "follower": follower_size})
        continue
    
    expected = leader_size * copy_ratio
    diff = expected - follower_size
    
    if abs(diff) > 0.01:  # 需要调整
        # 获取价格
        price = float(all_mids.get(coin, 0))
        notional = abs(diff) * price if price > 0 else 0
        total_notional += notional
        
        need_adjustment.append({
            'coin': coin,
            'leader': leader_size,
            'follower': follower_size,
            'expected': expected,
            'diff': diff,
            'price': price,
            'notional': notional
        })

print(f"需要调整的交易对数量: {len(need_adjustment)}")
print(f"预计总名义金额: ${total_notional:,.2f}")
print()

# 显示需要调整的前10个
print("需要调整的交易对 (按名义金额排序，前10个):")
print(f"{'币种':<10} {'Leader':<12} {'Follower':<12} {'实际%':<8} {'期望':<12} {'差额':<12} {'名义$':<10}")
print("-" * 80)
for item in sorted(need_adjustment, key=lambda x: abs(x['notional']), reverse=True)[:10]:
    actual_ratio_pct = 0.0
    if item["leader"] != 0:
        try:
            actual_ratio_pct = (item["follower"] / item["leader"]) * 100.0
        except Exception:
            actual_ratio_pct = 0.0
    print(f"{item['coin']:<10} {item['leader']:<12.1f} {item['follower']:<12.1f} "
          f"{actual_ratio_pct:<8.2f} {item['expected']:<12.1f} {item['diff']:<12.1f} ${item['notional']:<9.1f}")

print()
print("实施方式：")
print("  - 开发自动调仓功能，在启动时一次性调整所有仓位")
print("  - 优点：全自动，精确")
print("  - 缺点：需要开发和测试，有风险")
print()
if follower_only:
    print("⚠️ Follower 有但 Leader 已空仓的币种（可能是历史残留/漏平）：")
    for item in follower_only:
        print(f"  - {item['coin']}: follower_size={item['follower']}")
    print()

# 方案2：清空重来
print("方案2：【清空重来】")
print("-" * 80)
print(f"当前Follower仓位数量: {len(follower_positions)}")

follower_notional = 0
for coin, size in follower_positions.items():
    price = float(all_mids.get(coin, 0))
    follower_notional += abs(size) * price

print(f"需要平仓的名义金额: 约 ${follower_notional:,.2f}")
print()
print("实施步骤：")
print("  1. 停止copybot")
print("  2. 手动平掉所有Follower仓位")
print("  3. 清空日志（可选）")
print("  4. 重启copybot")
print("  5. 等待Leader开新仓，从零开始复制")
print()
print("优点：")
print("  - 最简单，无需开发")
print("  - 从零开始，比例一定正确")
print()
print("缺点：")
print("  - 需要手动操作")
print("  - 会错过当前Leader的仓位")
print("  - 如果Leader不重新开仓，就跟不上了")
print()

# 方案3：改进代码逻辑
print("方案3：【改进跟单逻辑】")
print("-" * 80)
print("问题：Leader平仓时，Follower没有仓位 → 跳过")
print("     Leader重新开仓，Follower只复制新单")
print()
print("改进方案：")
print("  A. 添加'仓位差异检测'：")
print("     - 定期检查Leader和Follower的仓位差异")
print("     - 如果差异超过阈值，自动补单/减仓")
print()
print("  B. 改进开仓逻辑：")
print("     - 开仓时不仅复制新交易的20%")
print("     - 检查总仓位，如果不足20%，额外补单")
print()
print("  C. 平仓时记录'缺失仓位'：")
print("     - Leader平仓但Follower没仓位时，记录这个'债务'")
print("     - 下次Leader开仓时，扣除这个'债务'，避免重复累积")
print()
print("优点：")
print("  - 从根本上解决问题")
print("  - 长期稳定")
print()
print("缺点：")
print("  - 需要较多开发工作")
print("  - 逻辑复杂，需要充分测试")
print()

# 推荐方案
print("🎯 推荐方案")
print("=" * 80)
print()
print("【短期 - 立即可用】方案2：清空重来")
print("  → 最快解决当前问题")
print("  → 确保后续复制正确")
print("  → 风险最低")
print()
print("【中期 - 需要开发】方案1：开发自动补单功能")
print("  → 在启动时检测并调整仓位")
print("  → 解决已有仓位不同步问题")
print("  → 适合有编程能力的用户")
print()
print("【长期 - 完整方案】方案3：改进跟单逻辑")
print("  → 添加定期仓位校验")
print("  → 自动修正偏差")
print("  → 防止未来再次出现比例问题")
print()

print("💡 具体建议：")
print("-" * 80)
print()
print("如果你想【立即解决】：")
print("  → 用方案2：清空所有仓位，重新开始")
print("  → 命令：可以写个脚本批量平仓")
print()
print("如果你想【保留现有仓位并修正】：")
print("  → 我可以帮你开发方案1的自动补单功能")
print("  → 需要10-20分钟开发和测试")
print()
print("如果你想【长期稳定】：")
print("  → 实现方案3，添加智能仓位监控")
print("  → 需要1-2小时开发")
print()

print("你想选择哪个方案？")
