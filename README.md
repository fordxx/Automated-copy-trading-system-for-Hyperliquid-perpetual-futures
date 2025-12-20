# Hyperliquid Copy Trader

自动跟单Hyperliquid交易所链上地址的交易系统。

## 功能特性

- 🔍 **实时监控**: 监控指定地址的链上交易
- 🤖 **自动跟单**: 根据配置比例自动复制交易
- ⚡ **低延迟**: 使用Hyperliquid的高性能API
- 🔔 **Telegram通知**: 实时推送交易和状态通知
- 🛡️ **风险控制**: 内置止损和最大仓位限制
- 📊 **状态监控**: 实时显示仓位和盈亏情况

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制 `config/config.yaml` 并修改配置：

```yaml
# 监控的地址
target_address: "0x..."

# 排除的地址列表 (可选)
exclude_addresses:
  - "0x你的地址"

# 跟单配置
copy_ratio: 0.1  # 跟单比例: 0.1 = 跟单目标交易大小的10%
max_position_size: 1.0  # 最大单笔仓位大小限制

# Hyperliquid配置
hyperliquid:
  account_address: "0x..."
  private_key: "0x..."
  use_testnet: false
```

## 使用

```bash
python scripts/run_copy_trader.py
```

## 安全注意事项

- 从极小的跟单比例开始测试 (0.001 = 0.1%)
- 设置合理的跟单比例，避免过度集中
- 监控账户风险，设置止损机制
- 不要使用主钱包私钥，使用专门的交易钱包
- 定期检查系统运行状态和交易记录