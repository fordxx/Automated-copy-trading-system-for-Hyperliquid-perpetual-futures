# Hyperliquid Copy Trader 仓位同步问题 - AI 接手提示词

## 项目背景

这是一个 Hyperliquid 交易所的自动跟单系统，用于复制目标地址（Leader）的交易。

- **项目路径**: `/home/fordxx/perp-tools/copybot`
- **语言**: Python 3
- **主要依赖**: hyperliquid-python-sdk
- **配置文件**: `.env`, `config/config.yaml`

## 当前问题

系统正常接收并复制新交易信号（每笔都正确复制20%），但**总仓位比例严重偏离**。

### 问题数据示例

| 交易对 | Leader总仓位 | Follower总仓位 | 实际比例 | 期望比例 |
|--------|-------------|---------------|---------|---------|
| ANIME | -1,156,871 | -10,000 | 0.86% | 20% |
| BOME | -3,442,340 | -311,149 | 9.04% | 20% |
| PENGU | -221,606 | -2,216 | 1.00% | 20% |
| POPCAT | -24,637 | 0 | 0% | 20% |

**需要调整**: 26个交易对，总计约 $6,497 名义金额

### 根本原因

1. **Leader平仓时，Follower没有仓位** → 系统跳过平仓信号（设计如此）
2. **Leader重新开仓** → Follower只复制新交易的20%
3. **结果**: Leader总仓位 = 历史累积，Follower仓位 = 只有最近几笔

**日志证据**:
- 41次ANIME平仓被跳过（`SKIP CLOSE (no follower position)`）
- 多次开仓失败（`Order has invalid size`）
- 系统运行时间：1天10小时（进程ID: 2492693）

## 需要实现的功能

### 方案1：仓位同步脚本（推荐优先实现）

创建一个独立的仓位同步工具，功能如下：

✅ **已实现**：`scripts/sync_positions.py`

#### 核心功能
1. **检测仓位差异**
   - 获取Leader和Follower的当前仓位
   - 计算每个币种的期望仓位（Leader × 20%）
   - 找出差异超过阈值的币种

2. **生成调整计划**
   - 需要补单的币种和数量
   - 需要减仓的币种和数量
   - 计算总名义金额
   - 考虑交易所限制（szDecimals、最小10美元等）

3. **执行调整**（需要用户确认）
   - 批量下单补充不足的仓位
   - 支持干运行模式（dry-run）
   - 显示进度和结果

#### 技术要求

**API使用**:
```python
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# 获取仓位
info = Info(constants.MAINNET_API_URL, skip_ws=True)
user_state = info.user_state(address)
positions = user_state.get('assetPositions', [])

# 下单
exchange = Exchange(wallet, base_url=constants.MAINNET_API_URL)
result = exchange.market_open(coin, is_buy, sz)
```

**环境变量**:
```bash
HYPERLIQUID_ACCOUNT_ADDRESS=0xYourFollowerWalletExample123456789
TARGET_ADDRESS=0xLeaderAddressExample123456789ABCDEF
HYPERLIQUID_PRIVATE_KEY=<私钥>
COPY_RATIO=0.2
MAX_NOTIONAL_PER_TRADE_USD=2000
MIN_TRADE_SIZE=0.01
```

**交易所限制**:
- 每个币种有不同的 `szDecimals`（通过 `info.meta()` 获取）
- 最小订单名义金额：$10
- 需要向下取整到允许的精度

#### 实现建议

文件位置: `scripts/sync_positions.py`

使用方法：
```bash
python scripts/sync_positions.py --dry-run   # 只显示计划（默认）
python scripts/sync_positions.py --execute   # 执行（会要求输入 yes 二次确认）
python scripts/sync_positions.py --execute --force  # 执行（跳过二次确认）
```

```python
#!/usr/bin/env python3
"""
仓位同步工具 - 调整Follower仓位到期望比例

使用方法:
  python scripts/sync_positions.py --dry-run  # 只显示计划，不执行
  python scripts/sync_positions.py --execute  # 执行调整
  python scripts/sync_positions.py --force    # 强制执行，跳过确认
"""

import argparse
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
# ... 其他导入

def get_position_diff():
    """计算仓位差异"""
    # 获取Leader和Follower仓位
    # 计算期望仓位
    # 返回需要调整的列表
    pass

def validate_adjustment(coin, size, price):
    """验证调整是否符合交易所规则"""
    # 检查szDecimals
    # 检查最小订单金额
    # 检查最大仓位限制
    pass

def execute_adjustment(adjustments, dry_run=True):
    """执行仓位调整"""
    # 遍历调整列表
    # 下市价单
    # 记录结果
    pass

if __name__ == "__main__":
    # 解析参数
    # 计算差异
    # 显示计划
    # 执行（如果需要）
```

### 方案2：改进主程序逻辑（长期改进）

修改 `src/position_manager.py`，添加仓位监控功能。

✅ **已实现（可选启用）**：主程序已加入定时“仓位纠偏（Position Sync）”后台任务（带价格门控）。
通过环境变量开启：
```bash
POSITION_SYNC_ENABLED=true
POSITION_SYNC_INTERVAL_S=300            # 每次检查间隔（秒）
POSITION_SYNC_PRICE_REF_MODE=strict_fill_open  # 更严格：用 leader 最近一次 OPEN 成交价做参考，且要求“当前价格严格更优”
POSITION_SYNC_FILL_REF_FALLBACK=skip    # 严格模式下拿不到参考成交价时：skip（跳过）/ entry（回退用 entryPx）
POSITION_SYNC_ALLOW_WORSE_PCT=0.0       # entryPx 模式下的容忍度；strict_fill_open 模式下不使用
POSITION_SYNC_GATE_REDUCTIONS=false     # 默认减仓不受价格门控影响（更安全）
POSITION_SYNC_MIN_REL_DIFF=0.05         # 目标与实际偏离超过 5% 才尝试纠偏
POSITION_SYNC_MIN_NOTIONAL_USD=10       # 最小名义金额（USD）
POSITION_SYNC_SPREAD_GATE_ENABLED=false # 额外门控（默认关闭）：点差过大时不纠偏
POSITION_SYNC_MAX_SPREAD_BPS=0          # 点差阈值（bps），例如 30 表示 0.30%
```

#### 需要修改的位置

**1. 添加定期仓位检查**

在 `src/copy_trader.py` 的主循环中添加：

```python
# 在主循环中添加定期检查
async def _position_monitor_loop(self):
    """定期检查仓位差异并自动调整"""
    while self.running:
        await asyncio.sleep(300)  # 每5分钟检查一次
        
        try:
            # 获取Leader和Follower仓位
            # 计算差异
            # 如果差异超过阈值（例如5%），自动调整
            pass
        except Exception as e:
            logger.error(f"Position monitor error: {e}")
```

**2. 改进开仓逻辑**

在 `execute_copy_trade` 中，开仓时检查总仓位：

```python
# 开仓前检查当前总仓位
current_position = self.get_position(coin)
leader_total_position = <从API获取>

expected_total = leader_total_position * copy_ratio
actual_total = current_position.size if current_position else 0

# 如果实际仓位小于期望，额外补单
if abs(actual_total) < abs(expected_total) * 0.95:  # 允许5%误差
    additional_size = expected_total - actual_total
    # 补单逻辑
```

## 关键代码位置

### 仓位管理
- **文件**: `src/position_manager.py`
- **关键方法**:
  - `execute_copy_trade()`: 执行跟单交易（第254-620行）
  - `get_position()`: 获取仓位（第248-250行）
  - `_market_open()`: 市价开仓（第662-735行）

### 主程序
- **文件**: `src/copy_trader.py`
- **关键方法**:
  - `run()`: 主循环（第550-700行）
  - `_handle_trade_batch()`: 处理交易批次（第1101-1250行）

### 配置加载
- **文件**: `src/copy_trader.py`
- **方法**: `_load_config()` (第145-245行)

## 测试要求

### 1. 仓位同步脚本测试

```bash
# 1. Dry-run测试
python scripts/sync_positions.py --dry-run

# 预期输出:
# - 显示所有需要调整的交易对
# - 显示调整数量和名义金额
# - 不执行任何交易

# 2. 小额测试
# 选择一个小额币种（例如VINE, YZY）测试实际执行

# 3. 完整测试
python scripts/sync_positions.py --execute
```

### 2. 主程序集成测试

```bash
# 1. 清空现有仓位
# 2. 重启copybot
# 3. 观察日志，确认仓位监控功能工作
# 4. 检查仓位比例是否保持在20%附近
```

## 安全注意事项

⚠️ **重要**:

1. **私钥安全**: 永远不要在日志或输出中显示私钥
2. **金额限制**: 建议先在小额测试，确认无误后再大规模执行
3. **Dry-run优先**: 任何批量操作都应先运行dry-run模式
4. **备份**: 执行前记录当前仓位状态
5. **市场风险**: 补单时会以市价成交，需要考虑滑点

## 调试信息

### 查看日志
```bash
tail -f logs/copy_trader.log
grep "SKIP CLOSE" logs/copy_trader.log | wc -l  # 查看跳过的平仓数
grep "invalid size" logs/copy_trader.log  # 查看失败的订单
```

### 查看当前进程
```bash
ps aux | grep copy_trader
# 当前进程: 2492693, 运行时间: 1天10小时
```

### 获取实时仓位
```bash
python3 << 'EOF'
from hyperliquid.info import Info
from hyperliquid.utils import constants
import os
from dotenv import load_dotenv

load_dotenv()
info = Info(constants.MAINNET_API_URL, skip_ws=True)

address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')
state = info.user_state(address)

for pos in state.get('assetPositions', []):
    coin = pos['position']['coin']
    size = pos['position']['szi']
    print(f"{coin}: {size}")
EOF
```

## 相关文档

- 项目README: `README.md`
- 配置指南: `ENV_SETUP_GUIDE.md`
- 比例说明: `COPY_RATIO_GUIDE.md`
- Hyperliquid API文档: https://hyperliquid.gitbook.io/

## 预期输出示例

### Dry-run输出
```
🔧 仓位同步计划
==================================================
配置: COPY_RATIO=0.2, 期望比例=20%

需要调整的交易对: 26个
总名义金额: $6,496.60

调整计划:
币种         当前仓位      期望仓位      差额          操作          名义金额
----------------------------------------------------------------------------
ANIME        -10000       -231374      -221374       补空单        $1916.90
POPCAT       0            -4927        -4927         开空单        $397.30
PENGU        -2216        -44321       -42105        补空单        $378.40
...

⚠️  这是dry-run模式，不会执行任何交易
使用 --execute 参数执行实际调整
```

### 执行输出
```
🚀 开始执行仓位调整
==================================================

[1/26] ANIME: 补单 -221374 @ 市价
  → 订单提交成功, 成交: -221300 @ $0.00866
  ✅ 完成

[2/26] POPCAT: 开单 -4927 @ 市价
  → 订单提交成功, 成交: -4927 @ $0.0806
  ✅ 完成

...

📊 执行完成
成功: 24/26
失败: 2/26 (TRUMP: 名义金额不足$10, kPEPE: 名义金额不足$10)

新的仓位比例:
ANIME: 19.98% ✅
POPCAT: 20.00% ✅
...
```

## 快速开始指令

```bash
# 1. 进入项目目录
cd /home/fordxx/perp-tools/copybot

# 2. 激活虚拟环境
source .venv/bin/activate

# 3. 查看当前仓位差异（已有脚本）
.venv/bin/python analyze_solutions.py

# 4. 创建并测试同步脚本
.venv/bin/python scripts/sync_positions.py --dry-run

# 5. 执行同步（确认无误后）
.venv/bin/python scripts/sync_positions.py --execute
```

## 当前实现状态（已落地）

### 1) 仓位纠偏（Position Sync）
- 主程序已加入定时纠偏（可选启用，默认更安全）：按 `Leader当前仓位 * COPY_RATIO` 计算目标仓位，并在满足价格门控时做补差。
- 价格门控（更严格）：默认 `POSITION_SYNC_PRICE_REF_MODE=strict_fill_open`（用 leader 最近一次 OPEN 成交价做参考，当前 mid 需“严格更优”）。
- 防打架：`POSITION_SYNC_SKIP_RECENT_TRADE_S`（leader 刚成交的币短时间不纠偏）。
- 点差门控（默认关闭）：`POSITION_SYNC_SPREAD_GATE_ENABLED` + `POSITION_SYNC_MAX_SPREAD_BPS`。
- 手动干预语义：手动把某币平到 0 后，纠偏不会再补回（直到 leader 该币仓位归零才解锁重置）。

### 2) 断线恢复补单（Catch-up）
- 为避免“重启/重连重复开仓导致仓位翻倍”，默认 **不回放 OPEN**：`CATCHUP_REPLAY_OPENS=false`（只回放 CLOSE 更安全）。
- Catch-up 仍可开启 Telegram 二次确认（YES/CONFIRM）。

### 3) 最小 $10 名义金额拒单的处理
- 已增加平仓缓冲：遇到 `Order must have minimum value of $10` 的小额平仓请求不会再报错刷屏，而是缓存等待凑够再平（见 `MIN_ORDER_NOTIONAL_USD`）。

### 4) Telegram 降噪
- 对 `skipped`（如“无仓位平仓”“数量过小”）做节流：`TELEGRAM_SKIPPED_TRADE_THROTTLE_S`。

## 联系方式

如有问题，请检查：
1. 日志文件: `logs/copy_trader.log`
2. 环境变量: `.env` 文件
3. 配置文件: `config/config.yaml`

---

**最后更新**: 2025-12-26
**问题状态**: 已解决（仓位同步/纠偏已实现并上线运行）
