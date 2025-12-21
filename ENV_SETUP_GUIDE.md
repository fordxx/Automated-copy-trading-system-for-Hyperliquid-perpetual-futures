# Hyperliquid Copy Trader - 环境变量快速设置指南

## 🚀 快速开始

### 1. 复制环境变量模板
```bash
cp .env.template .env
```

### 2. 编辑环境变量文件
```bash
nano .env
```

### 3. 填入你的配置信息

#### 必需配置：
```bash
# 目标跟单地址（你想复制的交易者地址）
TARGET_ADDRESS=0x替换为目标地址

# 你的Hyperliquid账户信息
HYPERLIQUID_ACCOUNT_ADDRESS=0x你的钱包地址
HYPERLIQUID_PRIVATE_KEY=0x你的私钥_保持绝对安全

# 网络环境 (mainnet 或 testnet)
HYPERLIQUID_ENV=mainnet
```

#### 可选配置：
```bash
# 如果你也交易Hyperliquid，避免复制自己的交易
EXCLUDE_ADDRESSES=0x你的钱包地址

# 跟单比例 (0.1 = 10%)
COPY_RATIO=0.1

# Telegram通知 (可选)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=从BotFather获取的令牌
TELEGRAM_CHAT_ID=你的Telegram用户ID
```

### 4. 验证配置
```bash
./scripts/validate_env.sh
```

### 5. 启动交易器
```bash
python scripts/run_copy_trader.py --env
```

## 🔑 如何获取所需信息

### Hyperliquid账户信息
1. 访问 [Hyperliquid](https://app.hyperliquid.xyz)
2. 连接你的钱包
3. 在设置中找到你的账户地址和私钥

### Telegram机器人设置
1. 向 [@BotFather](https://t.me/botfather) 发送 `/newbot`
2. 按照指示创建机器人，获取 `BOT_TOKEN`
3. 向 [@userinfobot](https://t.me/userinfobot) 发送消息获取你的 `CHAT_ID`

### 目标地址
- 从Hyperliquid交易界面或其他交易者分享的地址获取
- 确保地址格式正确（42位十六进制，以0x开头）

## ⚠️ 安全提醒

- 🔐 **私钥安全**：永远不要分享你的私钥
- 🧪 **从小额开始**：先用小比例测试 (0.001 = 0.1%)
- 📊 **监控风险**：定期检查仓位和盈亏
- 💰 **资金管理**：不要投入超出承受能力的资金
- 🔄 **定期备份**：备份你的配置（不包含私钥）

## 🛠️ 故障排除

### 配置验证失败
```bash
./scripts/validate_env.sh
```
检查错误信息并修正相应的环境变量。

### 启动失败
- 确保所有必需的环境变量都已设置
- 检查私钥和地址格式是否正确
- 验证网络连接

### Telegram通知不工作
- 确认 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 正确
- 向机器人发送 `/start` 消息激活对话

## 📚 更多信息

- 查看完整文档：`README.md`
- 配置验证脚本：`scripts/validate_env.sh`
- Telegram设置脚本：`scripts/setup_telegram.sh`