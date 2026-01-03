# Hyperliquid Copy Trader - 5分钟快速上手

![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)
![Difficulty](https://img.shields.io/badge/difficulty-⭐%20入门-green.svg)

**目标读者：** 新手用户、首次使用者
**预计时间：** 5-10 分钟
**前置要求：**
- Python 3.8+ 已安装
- 有 Hyperliquid 账户
- 基本的命令行操作能力

---

## 🎯 项目简介

自动跟单 Hyperliquid 交易所链上地址的专业交易系统。监控指定 Leader 的交易行为，按配置比例自动复制到您的账户。

### ✨ 核心亮点

- 🔍 **双监控架构**: WebSocket 实时 + REST API 备份，确保零遗漏
- 🤖 **智能跟单**: 支持固定比例（Position）和动态比例（Wallet）两种模式
- ⚡ **毫秒级延迟**: WebSocket 优先，实时响应交易
- 🛡️ **多重风控**: 止损、最大仓位、翻仓安全、价格门控
- 📊 **实时监控**: 监控面板、交易报表、健康告警
- 💼 **多实例支持**: 一台服务器同时跟踪多个 Leader

---

## 🚀 5步快速开始

### 步骤 1️⃣：安装依赖 (1分钟)

```bash
# 进入项目目录
cd /home/fordxx/perp-tools/copybot

# 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 验证安装
python -c "from hyperliquid.info import Info; print('✅ 安装成功!')"
```

### 步骤 2️⃣：配置环境变量 (2分钟)

**推荐使用 `.env` 文件**（更安全，适合后台运行）

```bash
# 1. 复制模板
cp .env.template .env

# 2. 编辑配置（使用您喜欢的编辑器）
nano .env
# 或
vim .env
```

**⚠️ 必须配置的关键项：**

```bash
# === 必需配置 ===
TARGET_ADDRESS=0xLeader钱包地址          # 要跟单的Leader地址
HYPERLIQUID_ACCOUNT_ADDRESS=0x您的地址   # 您的Hyperliquid钱包地址
HYPERLIQUID_PRIVATE_KEY=0x您的私钥       # 您的私钥（严格保密！）
HYPERLIQUID_ENV=mainnet                  # mainnet 或 testnet

# === 跟单配置 ===
COPY_MODE=position                       # position(固定比例) 或 wallet(动态比例)
COPY_RATIO=0.01                          # 🚨 首次建议从 0.01 (1%) 开始！

# === 可选但推荐 ===
MAX_POSITION_SIZE=1.0                    # 单币种最大仓位
MAX_NOTIONAL_PER_TRADE_USD=500          # 单笔最大金额（USD）
TELEGRAM_ENABLED=true                    # 启用通知
TELEGRAM_BOT_TOKEN=你的Bot令牌
TELEGRAM_CHAT_ID=你的ChatID
```

**💡 提示：** 首次使用请从**极小比例**开始（0.001 = 0.1%），确认系统稳定后再逐步提高！

### 步骤 3️⃣：验证配置 (30秒)

```bash
# 验证环境变量配置
./scripts/validate_env.sh

# 如果使用 YAML 配置，也可以验证
./scripts/check_config.sh
```

**预期输出：**
```
✅ TARGET_ADDRESS: 0x...
✅ HYPERLIQUID_ACCOUNT_ADDRESS: 0x...
✅ HYPERLIQUID_PRIVATE_KEY: *** (已配置)
✅ COPY_MODE: position
✅ COPY_RATIO: 0.01
...
✅ 所有配置验证通过！
```

### 2.2 也可以使用 YAML（可选）

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
  private_key: "__FROM_ENV__"  # 推荐：从 .env 读取 HYPERLIQUID_PRIVATE_KEY
  use_testnet: false  # 使用主网
```

💡 **多实例（multi-trader）建议**：不要把私钥写在 `config/my_multi.yaml`，改放到 `.env`：

- 实例 `name=trader_1` → `HYPERLIQUID_PRIVATE_KEY_TRADER_1=0x...`
- 然后用 `./scripts/validate_env.sh --multi --config config/my_multi.yaml` 检查

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

### 步骤 4️⃣：测试 Telegram 通知（可选，1分钟）

如果启用了 Telegram 通知，先测试一下：

```bash
# 激活虚拟环境（如果还没激活）
source .venv/bin/activate

# 测试 Telegram 通知
python scripts/test_telegram.py YOUR_BOT_TOKEN YOUR_CHAT_ID
```

**如何获取 Telegram 配置？**
1. 找 [@BotFather](https://t.me/botfather)，发送 `/newbot` 创建 Bot，获取 `BOT_TOKEN`
2. 找 [@userinfobot](https://t.me/userinfobot)，发送任意消息，获取 `CHAT_ID`

### 步骤 5️⃣：启动跟单程序 (1分钟)

**方式一：一键启动（🌟 推荐新手）**

```bash
# 启动交互式菜单
chmod +x scripts/manage_copy_trader.sh
./scripts/manage_copy_trader.sh
```

菜单提供的功能：
- ✅ 一键启动/停止/重启
- 📊 查看进程状态
- 📝 实时查看日志
- 🔍 搜索日志关键字

**方式二：命令行启动（快速）**

```bash
# 直接启动
./scripts/manage_copy_trader.sh start

# 查看状态
./scripts/manage_copy_trader.sh status

# 实时查看日志（Ctrl+C 退出，不会停止服务）
./scripts/manage_copy_trader.sh tail app

# 查看最近 100 行日志
./scripts/manage_copy_trader.sh last 100 app
```

**方式三：Python 脚本启动**

```bash
# 使用环境变量配置
python scripts/run_copy_trader.py --env

# 或使用 YAML 配置
python scripts/run_copy_trader.py --config config/my_config.yaml
```

---

## ✅ 验证运行

启动后，检查以下内容确认正常运行：

### 1. 检查进程状态

```bash
./scripts/manage_copy_trader.sh status
```

**预期输出：**
```
✅ Copy Trader 正在运行
PID: 12345
运行时间: 5 分钟
```

### 2. 查看日志

```bash
# 实时日志
./scripts/manage_copy_trader.sh tail app

# 或直接查看文件
tail -f logs/copy_trader.log
```

**正常日志示例：**
```
[INFO] Starting HyperliquidCopyTrader...
[INFO] WebSocket monitor started
[INFO] REST monitor started
[INFO] Monitoring Leader: 0x...
[INFO] Follower account: 0x...
[INFO] Copy mode: position, ratio: 0.01
```

### 3. Telegram 通知

如果启用了 Telegram，您应该会收到启动摘要：

```
🚀 Copy Trader 已启动

📋 配置摘要：
├─ Leader: 0x...abcd
├─ Follower: 0x...ef01
├─ 模式: Position (固定比例)
├─ 比例: 1.00%
└─ WebSocket: ✅ 已启用

📊 当前状态：
├─ Leader 仓位: 3个
├─ Follower 仓位: 3个
└─ 账户余额: $1,234.56

系统已就绪，开始监控...
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
# 查看实时日志（推荐）
./scripts/manage_copy_trader.sh tail app

# 或直接 tail 文件
tail -n 50 -f logs/copy_trader.log

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
