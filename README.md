# Hyperliquid Copy Trader

自动跟单Hyperliquid交易所链上地址的交易系统。

## 功能特性

### 核心功能
- 🔍 **实时监控**: 监控指定地址的链上交易
- 🤖 **自动跟单**: 根据配置比例自动复制交易
- ⚡ **低延迟**: 使用Hyperliquid的高性能API
- 🔔 **Telegram通知**: 实时推送交易和状态通知
- 🛡️ **风险控制**: 内置止损和最大仓位限制
- 📊 **状态监控**: 实时显示仓位和盈亏情况
- 🔧 **灵活配置**: 支持环境变量和配置文件两种配置方式

### 高级功能
- 💼 **多钱包多Leader** (v1.4.0): 使用不同钱包同时跟踪多个leader
- 📊 **双模式跟单** (v1.5.0): 支持固定比例和动态钱包比例两种模式
- 📝 **日志自动管理** (v1.3.0): 自动轮换和清理，保留7天
- 🔄 **进程自动重启**: 监控模式下自动恢复崩溃实例

### 运维工具 (v1.1.0新增)
- 📈 **实时监控面板**: 可视化显示系统状态和仓位比例
- 📊 **交易统计报表**: 日报/周报/月报,详细分析交易表现
- 🏥 **健康检查告警**: 自动检测异常并通过Telegram告警
- 🚀 **一键部署更新**: 简化代码更新和服务重启流程
- 🎯 **智能日志过滤**: 减少重复日志,提高可读性

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
- `COPY_MODE`: 跟单模式 (`position` 或 `wallet`，默认 `position`)
- `COPY_RATIO`: 跟单比例（0.1 = 10%，position模式使用）
- `TELEGRAM_BOT_TOKEN`: Telegram机器人令牌（可选）

**常用可选环境变量（建议了解）：**
- `MAX_POSITION_SIZE`: 单币种最大跟单仓位（合约数量上限）
- `MAX_NOTIONAL_PER_TRADE_USD`: 单笔跟单名义金额上限（USD）；>0 时会在 `COPY_RATIO` 之后再次截断
- `MIN_TRADE_SIZE`: 小于该数量的订单会被跳过（默认 0.01）
- `MIN_ORDER_NOTIONAL_USD`: 最小订单名义金额（USD，交易所限制；默认 10）；小额平仓会被缓存等待凑够
- `TRADE_BATCH_WINDOW_MS`: 交易批处理窗口（毫秒），降低 429 / 降噪
- `WEBSOCKET_IDLE_TIMEOUT_S`: WebSocket 空闲超时（秒），超时自动重连
- `WEBSOCKET_IDLE_LOG_INTERVAL_S`: WebSocket idle 重连告警日志节流（秒）
- `CATCHUP_REPLAY_OPENS`: 断线恢复补单是否回放 OPEN（默认 false，避免重复开仓导致仓位翻倍）
- `IGNORE_SIGINT_WHEN_DETACHED`: 后台运行时忽略 SIGINT（默认 true，避免 Ctrl+C / stray SIGINT 误停）
- `FLIP_WAIT_FOR_CLOSE`: 翻仓更稳模式（默认 true：先平再开，等待对侧仓位消失）
- `FLIP_WAIT_TIMEOUT_S`/`FLIP_WAIT_POLL_S`/`FLIP_OPEN_ON_TIMEOUT`: 翻仓等待细节
- `POSITION_SYNC_ENABLED`: 仓位纠偏（默认 false：定期把 follower 仓位拉回 leader*比例）
- `POSITION_SYNC_PRICE_REF_MODE`: 纠偏价格门控模式（推荐 `strict_fill_open`：当前 mid 必须严格更优）
- `POSITION_SYNC_SPREAD_GATE_ENABLED`/`POSITION_SYNC_MAX_SPREAD_BPS`: 点差门控（默认关闭，避免宽点差时纠偏）
- `POSITION_SYNC_SKIP_RECENT_TRADE_S`: 避免与实时成交打架（leader 刚成交的币短时间不纠偏）
- `POSITION_SYNC_MANUAL_CONFIRMATIONS`/`POSITION_SYNC_MANUAL_LOCK_UNTIL_LEADER_FLAT`: 降低“手动平仓”误判与锁定语义

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
  copy_mode: "position"  # "position"(固定比例) 或 "wallet"(动态钱包比例)
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
cd /home/fordxx/perp-tools/copybot
chmod +x scripts/manage_copy_trader.sh
./scripts/manage_copy_trader.sh
```

菜单里可以：启动/停止/重启、看进程、看日志。

### 命令行运维（不进菜单）

```bash
./scripts/manage_copy_trader.sh status
./scripts/manage_copy_trader.sh start
./scripts/manage_copy_trader.sh stop
./scripts/manage_copy_trader.sh restart

# 实时日志（按 Ctrl+C 退出查看，不会停服务）
./scripts/manage_copy_trader.sh tail app
./scripts/manage_copy_trader.sh tail stdout

# 最近 N 行
./scripts/manage_copy_trader.sh last 200 app
./scripts/manage_copy_trader.sh last 200 stdout
```

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

备注：通知消息使用 Markdown 格式。若 Telegram 返回 `can't parse entities`，可以先临时设置 `TELEGRAM_ENABLED=false`（不中断交易），再排查消息格式/转义问题。

## 交易执行与精度说明

- 程序会解析交易所返回结构中的 `statuses[].error`：有 error 会记为失败并输出 `Trade failed(...)`，避免“提示成功但实际拒单”。
- 部分币种合约数量只能是整数（例如 `szDecimals=0`）。程序会按 `szDecimals` 向下取整后再下单；如果日志仍出现 `Order has invalid size.`，优先检查该币种 `szDecimals` 是否正确缓存/刷新。

## 运维工具使用

### 实时监控面板

查看系统实时状态、仓位比例准确度:

```bash
# 完整模式
python scripts/monitor_dashboard.py

# 紧凑模式(适合终端)
python scripts/monitor_dashboard.py --compact --interval 5
```

### 交易统计报表

生成交易统计和性能分析:

```bash
# 今日报表
python scripts/trading_report.py --period today

# 周报
python scripts/trading_report.py --period week

# 自定义时间范围
python scripts/trading_report.py --custom 2025-12-20 2025-12-27
```

### 健康检查

检查系统健康状态,异常时发送告警:

```bash
# 单次检查
python scripts/health_check.py

# 持续监控(每10分钟检查,异常时告警)
python scripts/health_check.py --alert --continuous --interval 10
```

### 一键部署更新

从本地快速部署到服务器:

```bash
# 完整部署(同步代码+重启服务)
./scripts/deploy_update.sh

# 只查看操作,不实际执行
./scripts/deploy_update.sh --dry-run

# 只更新环境变量
./scripts/deploy_update.sh --env-only
```

详细使用说明请查看 [OPTIMIZATION_GUIDE.md](OPTIMIZATION_GUIDE.md)

## 多钱包多Leader跟单

使用不同的钱包同时跟踪多个leader的交易：

```bash
# 配置多个实例
cp config/multi_config.yaml config/my_multi.yaml
nano config/my_multi.yaml

# 使用管理脚本（推荐）
./scripts/manage_multi_trader.sh

# 或直接使用Python脚本
python scripts/run_multi_trader.py start   # 启动所有
python scripts/run_multi_trader.py status  # 查看状态
python scripts/run_multi_trader.py monitor # 监控模式（自动重启）
```

详细使用说明请查看 [MULTI_INSTANCE_GUIDE.md](MULTI_INSTANCE_GUIDE.md)

## 安全注意事项

- 从极小的跟单比例开始测试 (0.001 = 0.1%)
- 设置合理的跟单比例，避免过度集中
- 监控账户风险，设置止损机制
- 不要使用主钱包私钥，使用专门的交易钱包
- 定期检查系统运行状态和交易记录

## 相关文档

- [快速开始指南](QUICK_START.md) - 新手入门
- [多钱包快速参考](MULTI_WALLET_QUICK_START.md) - 1分钟上手多钱包
- [多实例跟单指南](MULTI_INSTANCE_GUIDE.md) - 多钱包多Leader详细配置
- [跟单模式指南](COPY_MODE_GUIDE.md) - Position vs Wallet模式详解
- [环境变量配置](ENV_SETUP_GUIDE.md) - 详细配置说明
- [跟单比例计算](COPY_RATIO_GUIDE.md) - 比例设置指南
- [优化工具使用](OPTIMIZATION_GUIDE.md) - 运维工具详解
- [服务器部署](SERVER_DEPLOY_GUIDE.md) - 服务器运维指南
- [AI接手文档](AI_HANDOFF_PROMPT.md) - 开发者文档
