# 跟单模式使用指南 (Copy Mode Guide)

## 概述

系统支持两种跟单模式，满足不同的风险管理需求：

1. **Position模式（仓位比例模式）** - 根据Leader开仓大小按固定比例跟单
2. **Wallet模式（钱包比例模式）** - 根据Follower和Leader的钱包余额比例动态跟单

---

## 1. Position模式（默认模式）

### 工作原理

按照**Leader开仓大小**乘以**固定比例**来计算Follower的开仓大小。

### 计算公式

```
Follower仓位大小 = Leader仓位大小 × copy_ratio
```

### 使用场景

- ✅ 适合固定资金比例跟单
- ✅ 可控的风险敞口
- ✅ 不受账户余额波动影响
- ✅ 适合长期稳定跟单

### 配置示例

```yaml
copy_trading:
  copy_mode: "position"  # 仓位比例模式
  copy_ratio: 0.1        # 10%比例
  max_position_size: 1.0
  min_trade_size: 0.01
  max_leverage: 5
```

### 环境变量配置

```bash
export COPY_MODE="position"
export COPY_RATIO="0.1"  # 10%
```

### 实际案例

**场景：**
- Leader开仓：100 USDC
- copy_ratio: 0.1 (10%)

**结果：**
- Follower开仓：10 USDC

**说明：**
无论Leader账户有1000 USDC还是10000 USDC，Follower始终按Leader**仓位的10%**跟单。

---

## 2. Wallet模式（钱包比例模式）

### 工作原理

每次交易时**动态计算** Follower和Leader的钱包余额比例，然后按这个比例跟单。

### 计算公式

```
实际比例 = Follower钱包余额 / Leader钱包余额
Follower仓位大小 = Leader仓位大小 × 实际比例
```

### 使用场景

- ✅ 适合按账户规模等比例跟单
- ✅ 自动调整风险敞口
- ✅ 保持与Leader相同的资金利用率
- ✅ 适合同步资金管理策略

### 配置示例

```yaml
copy_trading:
  copy_mode: "wallet"    # 钱包比例模式
  copy_ratio: 0.1        # 作为备用值（wallet模式会忽略此值）
  max_position_size: 2.0
  min_trade_size: 0.01
  max_leverage: 3
```

### 环境变量配置

```bash
export COPY_MODE="wallet"
export COPY_RATIO="0.1"  # 备用值，实际比例动态计算
```

### 实际案例

**场景1：等比例账户**
- Leader钱包：10,000 USDC
- Follower钱包：1,000 USDC
- 实际比例：1000/10000 = 0.1 (10%)
- Leader开仓：100 USDC

**结果：**
- Follower开仓：10 USDC (100 × 0.1)

**场景2：小账户**
- Leader钱包：10,000 USDC
- Follower钱包：500 USDC
- 实际比例：500/10000 = 0.05 (5%)
- Leader开仓：200 USDC

**结果：**
- Follower开仓：10 USDC (200 × 0.05)

**场景3：账户余额变化**
- 初始：Leader 10,000 USDC, Follower 1,000 USDC
- 交易1：比例 0.1，跟单 10 USDC
- 盈利后：Leader 11,000 USDC, Follower 1,100 USDC
- 交易2：比例自动调整为 1100/11000 = 0.1，仍然保持10%比例

**说明：**
Wallet模式会自动跟随账户余额变化，始终保持与Leader相同的**资金利用率**。

---

## 3. 两种模式对比

| 特性 | Position模式 | Wallet模式 |
|-----|-------------|-----------|
| **比例计算** | 固定比例 | 动态计算 |
| **依赖因素** | copy_ratio配置 | 实时钱包余额 |
| **API调用** | 较少 | 每次交易需查询Leader余额 |
| **适用场景** | 固定资金跟单 | 等比例资金管理 |
| **风险控制** | 手动调整比例 | 自动跟随余额变化 |
| **性能** | ⚡ 更快 | 🐢 稍慢（需额外API调用） |
| **推荐度** | ⭐⭐⭐⭐⭐ 默认推荐 | ⭐⭐⭐⭐ 进阶用法 |

---

## 4. 配置说明

### 单实例配置 (config/config.yaml)

```yaml
# 监控的目标地址
target_address: "0xLeaderAddressHere"

# 跟单配置
copy_trading:
  enabled: true
  # 选择模式: "position" 或 "wallet"
  copy_mode: "position"
  
  # Position模式：此值作为固定比例
  # Wallet模式：此值作为备用值（无法获取钱包余额时使用）
  copy_ratio: 0.1
  
  max_position_size: 1.0
  min_trade_size: 0.01
  max_leverage: 5

# Hyperliquid 配置
hyperliquid:
  account_address: "0xYourFollowerAddress"
  private_key: "__FROM_ENV__"
  use_testnet: false
```

### 多实例配置 (config/multi_config.yaml)

```yaml
trading_instances:
  # 实例1: Position模式跟单
  - name: "trader_position"
    enabled: true
    target_address: "0xLeaderAddress1"
    
    hyperliquid:
      account_address: "0xFollowerAddress1"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.1
      max_position_size: 1.0
      max_leverage: 5

  # 实例2: Wallet模式跟单
  - name: "trader_wallet"
    enabled: true
    target_address: "0xLeaderAddress2"
    
    hyperliquid:
      account_address: "0xFollowerAddress2"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "wallet"
      copy_ratio: 0.1  # 作为备用值
      max_position_size: 2.0
      max_leverage: 3
```

配套的 `.env`：
```bash
# 单实例：使用统一变量
HYPERLIQUID_PRIVATE_KEY=0x...

# 多实例：按实例名生成变量名（name 大写，非字母数字替换成 _）
HYPERLIQUID_PRIVATE_KEY_TRADER_POSITION=0x...
HYPERLIQUID_PRIVATE_KEY_TRADER_WALLET=0x...
```

---

## 5. 使用建议

### Position模式适合：

1. **新手用户** - 简单直接，易于理解
2. **固定资金跟单** - 想要严格控制每笔交易的大小
3. **低延迟需求** - 不需要额外API调用，速度更快
4. **稳定环境** - 不希望比例随账户余额波动

### Wallet模式适合：

1. **进阶用户** - 理解资金管理和动态比例
2. **等比例跟单** - 希望与Leader保持相同的资金利用率
3. **自动调整** - 账户余额变化时自动调整比例
4. **专业交易** - 追求与Leader相同的风险收益比

---

## 6. 注意事项

### Position模式

⚠️ **需要手动调整比例**
- 如果Follower账户增长/缩水，需手动修改`copy_ratio`

⚠️ **可能过度/不足跟单**
- 账户余额变化时，固定比例可能导致资金利用率失衡

### Wallet模式

⚠️ **需要额外API调用**
- 每次交易都要查询Leader钱包余额，可能稍慢

⚠️ **可能触发rate limit**
- 高频交易时可能增加API压力

⚠️ **失败时跳过交易**
- 如果无法获取Leader余额，该笔交易会被跳过（不执行）
- 不会降级到Position模式，避免使用错误比例

⚠️ **实时余额依赖**
- 如果Leader刚进行大额转账，可能影响比例计算准确性

---

## 7. 故障处理

### Wallet模式失败时的行为

如果Wallet模式无法获取Leader或Follower的账户余额：

1. 系统会**跳过该笔交易**（不执行）
2. 记录错误日志并说明原因
3. **不会降级到Position模式**（避免使用错误的比例下单）
4. 日志示例：
   ```
   ❌ Wallet mode failed (follower=None, leader=10000.00). 
   Skipping trade to avoid incorrect position size. Check network or API status.
   ```

**为什么不自动降级？**

如果自动降级到Position模式，可能导致严重问题：
- 示例：Follower账户100U，Leader账户10000U
- Wallet模式正确比例：0.01 (1%)
- 配置的copy_ratio：0.1 (10%)
- 如果降级使用0.1，会导致下单金额放大10倍！⚠️

**安全建议：**
- Wallet模式下如果频繁失败，检查网络连接
- 确保Leader地址正确且有余额
- 考虑添加重试机制或切换到Position模式（手动）

### 日志示例

**Wallet模式成功：**
```
💰 Wallet mode: Follower=1000.00U, Leader=10000.00U, Ratio=0.1000
```

**Wallet模式失败（跳过交易）：**
```
❌ Wallet mode failed (follower=None, leader=10000.00). 
Skipping trade to avoid incorrect position size. Check network or API status.
```

**为什么跳过而不是降级？**
```
危险示例:
  Follower账户: 100 USDC
  Leader账户: 10,000 USDC
  正确Wallet比例: 0.01 (1%)
  配置的copy_ratio: 0.1 (10%)
  
  Leader开仓: 1000 USDC
  
  ✅ Wallet模式正确: 1000 × 0.01 = 10 USDC
  ❌ 降级Position模式: 1000 × 0.1 = 100 USDC (超出账户！)
```

---

## 8. 常见问题 (FAQ)

### Q1: Wallet模式下，copy_ratio还有用吗？

**A:** 不再使用作为备用值。
- Wallet模式失败时会**跳过交易**，不会使用copy_ratio
- copy_ratio仅在Position模式下使用
- 建议：Wallet模式下可以设置为0，明确区分模式

### Q2: 我应该选择哪种模式？

**A:** 根据你的需求：
- **初学者/固定比例** → Position模式
- **进阶用户/动态跟单** → Wallet模式
- **不确定** → 先用Position模式，熟悉后再切换

### Q3: 可以实时切换模式吗？

**A:** 可以！
1. 修改配置文件中的`copy_mode`
2. 重启交易程序
3. 新的交易会使用新模式

### Q4: Wallet模式会影响性能吗？

**A:** 有轻微影响：
- 每次交易额外1个API调用（查询Leader余额）
- 增加约0.1-0.5秒延迟
- 对于正常跟单（非高频）影响很小

### Q5: 两种模式可以混用吗？

**A:** 在多实例配置下可以：
- 实例1用Position模式
- 实例2用Wallet模式
- 互不影响，独立运行

---

## 9. 快速开始

### 测试Position模式

```bash
# 修改配置
export COPY_MODE="position"
export COPY_RATIO="0.05"  # 5%

# 启动
python scripts/run_copy_trader.py
```

### 测试Wallet模式

```bash
# 修改配置
export COPY_MODE="wallet"

# 启动
python scripts/run_copy_trader.py
```

### 查看日志确认模式

```bash
tail -f logs/copy_trader.log | grep -E "Wallet mode|Position mode"
```

---

## 10. 总结

| 你需要... | 推荐模式 |
|----------|---------|
| 简单、快速、固定比例 | **Position** |
| 动态调整、等比例资金管理 | **Wallet** |
| 低延迟、高频跟单 | **Position** |
| 与Leader同步资金利用率 | **Wallet** |
| 初学者 | **Position** |
| 进阶用户 | **Wallet** |

两种模式各有优劣，根据你的交易策略和风险偏好选择合适的模式！

---

**更新日期：** 2025-12-30  
**版本：** v1.5.0
