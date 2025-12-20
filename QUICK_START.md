# Hyperliquid Copy Trader - 快速开始指南

## 项目概述

这是一个自动跟单Hyperliquid交易所链上地址交易的系统。通过监控指定地址的交易行为，自动复制到自己的账户中。

## 核心功能

- 🔍 **实时监控**: 监控指定地址的链上交易
- 🤖 **自动跟单**: 根据配置的比例自动复制交易
- ⚡ **低延迟**: 使用Hyperliquid的高性能API
- 🛡️ **风险控制**: 内置止损和最大仓位限制
- 📊 **状态监控**: 实时显示仓位和盈亏情况

## 快速开始

### 1. 环境准备

```bash
# 克隆或下载项目到 new_project 目录
cd new_project

# 运行设置脚本
chmod +x scripts/setup.sh
./scripts/setup.sh
```

### 2. 配置设置

```bash
# 复制配置文件
cp config/config.yaml config/my_config.yaml

# 编辑配置 (使用你喜欢的编辑器)
nano config/my_config.yaml
```

**关键配置项：**

```yaml
# 监控的地址 - 替换为你要跟单的地址
target_address: "0x实际地址"

# 排除的地址列表 - 避免跟单自己的交易或其他不需要的地址
exclude_addresses:
  - "0x你的地址"  # 如果你也在Hyperliquid交易，添加你的地址

# 跟单配置
copy_trading:
  copy_ratio: 0.1        # 跟单比例: 0.1 = 跟单目标交易大小的10%
  max_position_size: 1.0 # 最大单笔仓位大小限制 (合约数量)
```

📖 **详细说明**:
- 见 `COPY_RATIO_GUIDE.md` 了解跟单比例的完整计算逻辑和示例
- 见 `SELF_TRADING_GUIDE.md` 了解自己也在交易时的配置方法
🧮 **计算器工具**: 运行 `./scripts/calculate_copy_ratio.sh` 来测试不同配置的效果

```yaml
# 你的Hyperliquid账户信息
hyperliquid:
  account_address: "0x你的钱包地址"
  private_key: "0x你的私钥"
  use_testnet: false  # 使用主网
```

### 2.4 Telegram通知配置 (可选)

启用Telegram通知来实时接收交易提醒：

```yaml
# Telegram通知配置
telegram:
  enabled: true
  bot_token: "你的机器人令牌"  # 从 @BotFather 获取
  chat_id: "你的聊天ID"        # 从 @userinfobot 获取
```

**获取Telegram配置：**

1. **创建机器人**:
   - 在Telegram中找到 @BotFather
   - 发送 `/newbot` 创建新机器人
   - 保存机器人令牌 (bot_token)

2. **获取聊天ID**:
   - 在Telegram中找到 @userinfobot
   - 发送任意消息获取你的用户ID
   - 这个ID就是 chat_id

**安全配置 (推荐)：**

```bash
# 复制环境变量模板
cp .env.template .env

# 编辑环境变量文件 (更安全)
nano .env
```

### 2.6 配置验证

在启动程序前，运行配置检查：

```bash
# 运行配置检查脚本
./scripts/check_config.sh
```

确保所有配置都正确设置，没有警告或错误。

**详细的Telegram设置指南：**
```bash
./scripts/setup_telegram.sh
```

### 3. 测试运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 可选: 测试Telegram通知
python scripts/test_telegram.py YOUR_BOT_TOKEN YOUR_CHAT_ID

# 运行跟单程序
python scripts/run_copy_trader.py
```

## 安全提醒

⚠️ **重要安全注意事项：**

1. **小额开始**: 从非常小的 `copy_ratio` 开始 (0.001 = 0.1%)
2. **密钥安全**: 不要把私钥提交到版本控制，使用环境变量或加密存储
3. **资金管理**: 设置合理的 `max_position_size`，不要投入过多资金
4. **监控运行**: 定期检查日志和仓位状态，及时干预
5. **风险意识**: 跟单有风险，目标地址的交易不保证盈利

## 架构说明

```
src/
├── copy_trader.py      # 主程序入口
├── trade_monitor.py    # 交易监控模块
├── position_manager.py # 仓位管理模块
└── utils/
    └── helpers.py      # 辅助工具函数
```

## 故障排除

### 常见问题

1. **连接失败**: 检查网络和API密钥
2. **交易失败**: 确认账户有足够余额
3. **监控不到交易**: 确认目标地址有近期交易

### 日志查看

```bash
# 查看实时日志
tail -f logs/copy_trader.log

# 查看错误日志
grep ERROR logs/copy_trader.log
```

## 进阶配置

### 风险控制

```yaml
risk_management:
  max_drawdown: 0.1      # 最大回撤 10%
  stop_loss_ratio: 0.05  # 止损 5%
  take_profit_ratio: 0.1 # 止盈 10%
```

### 监控设置

```yaml
monitoring:
  poll_interval: 30      # 每30秒检查一次
  max_retries: 3         # 最大重试次数
```

## 开发和测试

```bash
# 运行单元测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_copy_trader.py::TestTradeMonitor::test_get_recent_trades
```

## 许可证

本项目仅供学习和研究使用。请遵守当地法律法规。

## 免责声明

使用本软件进行交易存在风险，包括但不限于资金损失风险。作者不对使用本软件造成的任何损失承担责任。请在充分了解风险后再使用。