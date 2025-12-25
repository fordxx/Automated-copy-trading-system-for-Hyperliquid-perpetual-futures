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

# 单币种最大仓位上限（合约数量）
MAX_POSITION_SIZE=1.0

# 单笔跟单名义金额上限（USD），>0 时会在 COPY_RATIO 之后再次截断
MAX_NOTIONAL_PER_TRADE_USD=0

# 小于该数量的订单会跳过（默认 0.01）
MIN_TRADE_SIZE=0.01

# 最小订单名义金额（USD，交易所限制；默认 10）
MIN_ORDER_NOTIONAL_USD=10

# 批处理窗口（ms）：目标地址短时间内多笔成交会被聚合，降低 429
TRADE_BATCH_WINDOW_MS=300

# WebSocket 空闲重连：目标地址长期没成交时可调大减少“idle 重连”刷屏
WEBSOCKET_IDLE_TIMEOUT_S=30
WEBSOCKET_IDLE_LOG_INTERVAL_S=300

# 断线恢复补单（Catch-up，可选）
# 安全建议：默认不要回放 OPEN（否则在重启/重连时可能重复开仓导致仓位翻倍），仅回放 CLOSE 更安全。
CATCHUP_ENABLED=true
CATCHUP_REPLAY_OPENS=false
CATCHUP_WINDOW_S=600
CATCHUP_MAX_TRADES=200
CATCHUP_MIN_INTERVAL_S=30
CATCHUP_START_DELAY_S=0
CATCHUP_REQUIRE_APPROVAL=false
CATCHUP_REPLAY_SPACING_S=2

# 后台运行时忽略 SIGINT，避免 Ctrl+C / stray SIGINT 误停（默认 true）
IGNORE_SIGINT_WHEN_DETACHED=true

# 翻仓更稳模式：先平再开（默认 true）
FLIP_WAIT_FOR_CLOSE=true
FLIP_WAIT_TIMEOUT_S=6
FLIP_WAIT_POLL_S=0.75
FLIP_OPEN_ON_TIMEOUT=false

# 仓位纠偏（Position Sync，可选，默认关闭）
# 定期对比 follower 当前仓位 vs leader 当前仓位 * COPY_RATIO，并在满足“价格门控”时补差。
POSITION_SYNC_ENABLED=false
POSITION_SYNC_INTERVAL_S=300
POSITION_SYNC_START_DELAY_S=30
POSITION_SYNC_MIN_REL_DIFF=0.05
POSITION_SYNC_MIN_NOTIONAL_USD=10
POSITION_SYNC_DEFAULT_LEVERAGE=5

# 更严格的价格门控（推荐）：用 leader 最近一次 OPEN 成交价做参考，且要求当前 mid “严格更优”
POSITION_SYNC_PRICE_REF_MODE=strict_fill_open
POSITION_SYNC_FILL_REF_FALLBACK=skip

# 若用 entryPx 模式：允许比参考价更差的容忍度（0 表示不更差）
POSITION_SYNC_ALLOW_WORSE_PCT=0.0

# 是否让“减仓/平仓”也受价格门控影响（默认 false：减仓更安全，允许直接执行）
POSITION_SYNC_GATE_REDUCTIONS=false

# 避免与实时成交打架：leader 某个币刚刚有成交时，短时间内跳过纠偏（秒）
POSITION_SYNC_SKIP_RECENT_TRADE_S=30

# 额外门控（默认关闭）：点差过大时不纠偏
POSITION_SYNC_SPREAD_GATE_ENABLED=false
POSITION_SYNC_MAX_SPREAD_BPS=0
# 点差拿不到时如何处理（仅在开启点差门控时生效）：skip / ignore
POSITION_SYNC_SPREAD_UNAVAILABLE_ACTION=skip

# 纠偏 planning 缓存（秒），降低 REST 压力
POSITION_SYNC_MIDS_TTL_S=2
POSITION_SYNC_FILLS_TTL_S=10
POSITION_SYNC_L2_TTL_S=2

# 严格门控可选回退：等待超过该秒数仍不“严格更优”时，回退为 entryPx 门控；0=不回退
POSITION_SYNC_STRICT_MAX_WAIT_S=0

# 手动干预冷却（默认关闭）：
# 如果你手动把某个币的仓位平掉，纠偏不会立刻把它“补回去”，而是冷却一段时间。
POSITION_SYNC_MANUAL_COOLDOWN_S=0
POSITION_SYNC_MANUAL_GRACE_S=30
# 需要连续 N 次刷新都确认“仓位已消失”才判定为手动干预（降低误判）
POSITION_SYNC_MANUAL_CONFIRMATIONS=2
# 更强的语义（推荐 true）：手动平掉后，不会通过“纠偏”补回，直到 leader 该币仓位归零才重置。
POSITION_SYNC_MANUAL_LOCK_UNTIL_LEADER_FLAT=true

# Telegram通知 (可选)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=从BotFather获取的令牌
TELEGRAM_CHAT_ID=你的Telegram用户ID

# 跳过类通知降噪（秒）：同一币种同一原因在窗口内只推送一次汇总
TELEGRAM_SKIPPED_TRADE_THROTTLE_S=300
```

### 4. 验证配置
```bash
./scripts/validate_env.sh
```

### 5. 启动交易器
```bash
python scripts/run_copy_trader.py --env
```

更推荐用管理脚本后台运行（更省事，也更不容易误停）：

```bash
chmod +x scripts/manage_copy_trader.sh
./scripts/manage_copy_trader.sh start
./scripts/manage_copy_trader.sh status

# 实时日志（按 Ctrl+C 退出查看，不会停服务）
./scripts/manage_copy_trader.sh tail app
./scripts/manage_copy_trader.sh tail stdout
```

## 📉 风险阈值语义（重要）

- `MAX_DRAWDOWN` / `STOP_LOSS_RATIO` 的默认语义是“比例”：例如 `0.1` 表示账户权益的 10%。
- 为兼容老配置：如果设置值 `> 1`，程序会把它当作“绝对美元阈值”。

示例：

```bash
# 回撤 10%，止损 5%
MAX_DRAWDOWN=0.10
STOP_LOSS_RATIO=0.05

# 或者：直接按美元止损（绝对值）
STOP_LOSS_RATIO=50
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
