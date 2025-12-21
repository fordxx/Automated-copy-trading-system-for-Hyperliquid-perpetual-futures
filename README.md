# Hyperliquid Copy Trader

自动跟单Hyperliquid交易所链上地址的交易系统。

## 功能特性

- 🔍 **实时监控**: 监控指定地址的链上交易
- 🤖 **自动跟单**: 根据配置比例自动复制交易
- ⚡ **低延迟**: 使用Hyperliquid的高性能API
- 🔔 **Telegram通知**: 实时推送交易和状态通知
- 🛡️ **风险控制**: 内置止损和最大仓位限制
- 📊 **状态监控**: 实时显示仓位和盈亏情况
- 🔧 **灵活配置**: 支持环境变量和配置文件两种配置方式

## 安装

```bash
pip install -r requirements.txt
```

## 配置

### 方式一：环境变量配置（推荐）

1. 复制环境变量模板：
```bash
cp .env.template .env
```

2. 编辑 `.env` 文件，填入你的配置：
```bash
nano .env
```

3. 验证配置：
```bash
./scripts/validate_env.sh
```

**主要环境变量：**
- `TARGET_ADDRESS`: 要跟单的目标地址
- `HYPERLIQUID_ACCOUNT_ADDRESS`: 你的Hyperliquid账户地址
- `HYPERLIQUID_PRIVATE_KEY`: 你的私钥（保密！）
- `COPY_RATIO`: 跟单比例（0.1 = 10%）
- `TELEGRAM_BOT_TOKEN`: Telegram机器人令牌（可选）

### 方式二：YAML配置文件

复制 `config/config.yaml` 并修改配置：

```yaml
# 监控的地址
target_address: "0x..."

# 排除的地址列表 (可选)
exclude_addresses:
  - "0x你的地址"

# 跟单配置
copy_trading:
  copy_ratio: 0.1  # 跟单比例: 0.1 = 跟单目标交易大小的10%
  max_position_size: 1.0  # 最大单笔仓位大小限制

# Hyperliquid配置
hyperliquid:
  account_address: "0x..."
  private_key: "0x..."
  use_testnet: false
```

## 使用

### 一键启动（推荐：带菜单）

最省事的方式：

```bash
cd new_project
chmod +x scripts/manage_copy_trader.sh
./scripts/manage_copy_trader.sh
```

菜单里可以：启动/停止/重启、看进程、看日志。

### 使用环境变量：
```bash
# 仅使用环境变量
python scripts/run_copy_trader.py --env

# 或使用默认配置（优先环境变量）
python scripts/run_copy_trader.py
```

### 使用配置文件：
```bash
# 指定配置文件
python scripts/run_copy_trader.py --config config/config.yaml
```

### 验证配置：
```bash
# 验证环境变量
./scripts/validate_env.sh

# 验证配置文件
python scripts/check_config.sh
```

## Telegram通知设置

1. 创建Telegram机器人：
   - 向 [@BotFather](https://t.me/botfather) 发送 `/newbot`
   - 获取 `TELEGRAM_BOT_TOKEN`

2. 获取Chat ID：
   - 向 [@userinfobot](https://t.me/userinfobot) 发送消息
   - 或向你的机器人发送消息，然后访问 `https://api.telegram.org/bot<YourBOTToken>/getUpdates`

3. 配置环境变量：
```bash
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 安全注意事项

## 安全注意事项

- 从极小的跟单比例开始测试 (0.001 = 0.1%)
- 设置合理的跟单比例，避免过度集中
- 监控账户风险，设置止损机制
- 不要使用主钱包私钥，使用专门的交易钱包
- 定期检查系统运行状态和交易记录