# Hyperliquid Copy Trader

![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

自动跟单 Hyperliquid 交易所链上地址的专业交易系统。通过实时监控目标地址交易，按配置比例自动复制到您的账户。

## ✨ 核心特性

### 🎯 交易核心
- **🔍 双监控架构**: WebSocket实时推送 + REST API轮询备份，确保零遗漏
- **⚡ 超低延迟**: WebSocket优先模式，毫秒级交易响应
- **🤖 智能跟单**: 支持 Position（固定比例）和 Wallet（动态余额比例）两种模式
- **🛡️ 交易去重**: 中心化去重机制，REST 和 WebSocket 共享，避免重复执行
- **📦 批处理聚合**: 高频交易自动聚合，减少API限制和订单拥挤

### 🔒 风险管理
- **💰 多维度风控**: 最大仓位、单笔限额、最小下单量等多重保护
- **🎚️ 价格门控**: 仓位同步时可设置价格基准，避免不利价格成交
- **📊 点差门控**: 超宽点差时自动跳过纠偏，保护资金
- **🔄 翻仓安全**: 先平后开模式，等待对侧仓位完全消失再反向开仓
- **⏰ 止损止盈**: 可配置自动止损比例和触发后操作

### 🚀 高级功能
- **💼 多钱包多Leader** (v1.4.0): 同时运行多个独立实例，每个实例独立跟单
- **📊 双模式跟单** (v1.5.0): Position 固定比例 / Wallet 动态钱包余额比例
- **🔄 仓位同步纠偏**: 定期对比并修正 Follower 与 Leader*比例的偏差
- **🔁 断线自动补单**: WebSocket断线恢复后自动回补遗漏交易（可配置）
- **📝 日志自动管理**: 按天轮换，自动清理旧日志，支持cron定期清理

### 🛠️ 运维工具套件 (v1.1.0+)
- **📈 实时监控面板**: 可视化显示系统状态、仓位比例准确度、P&L
- **📊 交易统计报表**: 日报/周报/月报，详细分析交易表现和成功率
- **🏥 健康检查告警**: 持续监控系统健康，异常时 Telegram 自动告警
- **🚀 一键部署更新**: 本地到服务器快速部署，支持代码/配置同步和服务重启
- **🎯 智能日志过滤**: 自动节流重复日志，降低噪音，提高可读性

## 📦 快速安装

### 环境要求
- Python 3.8 或更高版本
- pip 包管理器
- Linux/macOS/WSL（推荐）

### 安装步骤

```bash
# 1. 克隆项目（如果还没有）
cd /home/fordxx/perp-tools/copybot

# 2. 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 验证安装
python -c "from hyperliquid.info import Info; print('安装成功!')"
```

## ⚙️ 配置指南

### 方式一：环境变量配置（✅ 推荐用于生产环境）

环境变量配置更适合后台运行，程序会自动从项目根目录加载 `.env` 文件。

```bash
# 1. 复制环境变量模板
cp .env.template .env

# 2. 编辑配置文件
nano .env  # 或使用您喜欢的编辑器

# 3. 验证配置
./scripts/validate_env.sh
```

**📌 必需配置：**
```bash
TARGET_ADDRESS=0x...                        # 要跟单的Leader地址
HYPERLIQUID_ACCOUNT_ADDRESS=0x...          # 您的Hyperliquid钱包地址
HYPERLIQUID_PRIVATE_KEY=0x...              # 您的私钥（严格保密！）
HYPERLIQUID_ENV=mainnet                    # mainnet 或 testnet
```

**⚙️ 跟单模式配置：**
```bash
COPY_MODE=position                         # position(固定比例) 或 wallet(动态钱包比例)
COPY_RATIO=0.1                             # 跟单比例(0.1=10%)，position模式使用
MAX_POSITION_SIZE=1.0                      # 单币种最大仓位（合约数量）
MAX_NOTIONAL_PER_TRADE_USD=1000           # 单笔交易最大名义金额（USD）
MIN_TRADE_SIZE=0.01                        # 最小下单量
MIN_ORDER_NOTIONAL_USD=10                  # 最小订单金额（交易所限制）
```

**⚡ 性能与延迟优化：**
```bash
USE_WEBSOCKET=true                         # 启用WebSocket实时监控（推荐）
TRADE_BATCH_WINDOW_MS=500                  # 批处理窗口(ms)，聚合高频交易
WEBSOCKET_IDLE_TIMEOUT_S=30                # WebSocket空闲超时（秒）
WEBSOCKET_IDLE_LOG_INTERVAL_S=300          # 重连日志节流间隔（秒）
```

**🔄 断线恢复配置：**
```bash
CATCHUP_ENABLED=true                       # 启用断线补单
CATCHUP_REPLAY_OPENS=false                 # 是否回放OPEN订单（默认false避免仓位翻倍）
CATCHUP_WINDOW_S=600                       # 补单时间窗口（秒）
CATCHUP_MAX_TRADES=200                     # 最大补单交易数
CATCHUP_REQUIRE_APPROVAL=false             # 是否需要Telegram确认
```

**📊 仓位同步纠偏（高级功能）：**
```bash
POSITION_SYNC_ENABLED=false                       # 启用仓位纠偏（默认关闭）
POSITION_SYNC_INTERVAL_S=300                      # 纠偏间隔（秒）
POSITION_SYNC_PRICE_REF_MODE=strict_fill_open     # 价格门控模式
POSITION_SYNC_SPREAD_GATE_ENABLED=false           # 点差门控
POSITION_SYNC_MAX_SPREAD_BPS=0                    # 最大点差（基点）
POSITION_SYNC_SKIP_RECENT_TRADE_S=30              # 跳过最近交易时间（秒）
POSITION_SYNC_MANUAL_LOCK_UNTIL_LEADER_FLAT=true  # 手动平仓后锁定
```

**🔒 翻仓安全配置：**
```bash
FLIP_WAIT_FOR_CLOSE=true                   # 翻仓时先平后开（推荐）
FLIP_WAIT_TIMEOUT_S=6                      # 等待超时时间（秒）
FLIP_WAIT_POLL_S=0.75                      # 轮询间隔（秒）
FLIP_OPEN_ON_TIMEOUT=false                 # 超时后是否仍开仓
```

**🔔 Telegram通知：**
```bash
TELEGRAM_ENABLED=true                      # 启用Telegram通知
TELEGRAM_BOT_TOKEN=...                     # Bot令牌
TELEGRAM_CHAT_ID=...                       # Chat ID
TELEGRAM_SKIPPED_TRADE_THROTTLE_S=300      # 跳过交易通知节流（秒）
```

**详细配置说明请查看：** [ENV_SETUP_GUIDE.md](ENV_SETUP_GUIDE.md)

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
  private_key: "__FROM_ENV__"  # 推荐：从 .env 读取 HYPERLIQUID_PRIVATE_KEY
  use_testnet: false
```

## 🚀 使用指南

### 一键启动（🌟 推荐：交互式菜单）

最简单的启动方式，适合新手：

```bash
cd /home/fordxx/perp-tools/copybot
chmod +x scripts/manage_copy_trader.sh
./scripts/manage_copy_trader.sh
```

**菜单功能：**
- ✅ 一键启动/停止/重启服务
- 📊 查看进程状态和PID
- 📝 实时查看日志
- 🔍 搜索日志中的关键字
- 🧹 清理旧日志文件

### 命令行运维（快速操作）

不进入菜单，直接执行命令：

```bash
# 服务管理
./scripts/manage_copy_trader.sh status      # 查看状态
./scripts/manage_copy_trader.sh start       # 启动服务
./scripts/manage_copy_trader.sh stop        # 停止服务
./scripts/manage_copy_trader.sh restart     # 重启服务

# 日志查看
./scripts/manage_copy_trader.sh tail app    # 实时应用日志
./scripts/manage_copy_trader.sh tail stdout # 实时标准输出
./scripts/manage_copy_trader.sh last 200 app  # 查看最近200行

# 注意：按 Ctrl+C 退出日志查看，不会停止服务
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

## 🛠️ 运维工具套件

### 📈 实时监控面板

可视化显示系统状态、仓位比例准确度、实时P&L：

```bash
# 完整模式（推荐终端宽度 > 120）
python scripts/monitor_dashboard.py

# 紧凑模式（适合小终端）
python scripts/monitor_dashboard.py --compact --interval 5
```

**显示内容：**
- 📊 实时仓位列表（Leader vs Follower）
- 💰 每个币种的P&L和比例准确度
- 📉 总账户价值和未实现盈亏
- ⚡ 实时刷新（默认10秒）

### 📊 交易统计报表

生成详细的交易统计和性能分析报告：

```bash
# 今日报表
python scripts/trading_report.py --period today

# 周报
python scripts/trading_report.py --period week

# 月报
python scripts/trading_report.py --period month

# 自定义时间范围
python scripts/trading_report.py --custom 2025-12-20 2025-12-27
```

**报表内容：**
- 交易成功率和失败原因统计
- 各币种交易频率和金额分布
- 最大盈利/亏损交易
- 平均持仓时间和收益率

### 🏥 健康检查与告警

自动检测系统异常并通过Telegram告警：

```bash
# 单次检查
python scripts/health_check.py

# 持续监控（每10分钟检查一次，异常时Telegram告警）
python scripts/health_check.py --alert --continuous --interval 10
```

**检查项目：**
- ✅ 进程是否运行
- ✅ API连接是否正常
- ✅ WebSocket连接状态
- ✅ 日志文件大小和最后更新时间
- ✅ 系统资源使用率

### 🚀 一键部署更新

从本地快速部署代码更新到服务器：

```bash
# 完整部署（同步代码 + 重启服务）
./scripts/deploy_update.sh

# 预演模式（查看操作，不实际执行）
./scripts/deploy_update.sh --dry-run

# 仅同步环境变量
./scripts/deploy_update.sh --env-only

# 仅同步代码，不重启服务
./scripts/deploy_update.sh --no-restart
```

**需要配置环境变量：**
```bash
COPYBOT_SERVER_IP=1.2.3.4
COPYBOT_SERVER_USER=ubuntu
COPYBOT_SSH_KEY=/path/to/ssh/key
COPYBOT_REMOTE_DIR=/home/ubuntu/copybot
```

### 🧹 日志管理工具

自动清理旧日志，释放磁盘空间：

```bash
# 手动清理7天前的日志
python scripts/clean_old_logs.py

# 设置定时任务（每天凌晨3点自动清理）
./scripts/setup_log_cleanup_cron.sh
```

**详细使用说明：** [OPTIMIZATION_GUIDE.md](OPTIMIZATION_GUIDE.md) | [SERVER_DEPLOY_GUIDE.md](SERVER_DEPLOY_GUIDE.md)

## 💼 多钱包多Leader跟单

**适用场景：** 使用不同的钱包同时跟踪多个Leader的交易，每个实例独立运行、独立配置。

### 快速开始

```bash
# 1. 复制多实例配置模板
cp config/multi_config.yaml config/my_multi.yaml
nano config/my_multi.yaml

# 2. 配置环境变量（推荐：私钥不写进YAML）
# 实例 name=trader_1 → 环境变量 HYPERLIQUID_PRIVATE_KEY_TRADER_1=0x...
# 实例 name=trader_2 → 环境变量 HYPERLIQUID_PRIVATE_KEY_TRADER_2=0x...

# 3. 验证配置
./scripts/validate_env.sh --multi --config config/my_multi.yaml

# 4. 启动（推荐：使用管理脚本）
./scripts/manage_multi_trader.sh
```

### 管理命令

```bash
# 使用Python脚本直接管理
python scripts/run_multi_trader.py start     # 启动所有实例
python scripts/run_multi_trader.py stop      # 停止所有实例
python scripts/run_multi_trader.py status    # 查看状态
python scripts/run_multi_trader.py monitor   # 监控模式（自动重启）
python scripts/run_multi_trader.py single trader_1  # 仅启动单个实例
```

**详细配置指南：**
- [MULTI_WALLET_QUICK_START.md](MULTI_WALLET_QUICK_START.md) - 1分钟快速上手
- [MULTI_INSTANCE_GUIDE.md](MULTI_INSTANCE_GUIDE.md) - 完整配置说明

---

## ⚠️ 安全注意事项

### 测试与风控
- 🧪 **小额测试**: 从极小比例开始 (`COPY_RATIO=0.001` = 0.1%)
- 📊 **逐步增加**: 确认系统稳定后再提高比例
- 🎯 **合理限额**: 设置 `MAX_POSITION_SIZE` 和 `MAX_NOTIONAL_PER_TRADE_USD`
- 🛡️ **启用止损**: 配置 `STOP_LOSS_RATIO` 保护资金

### 密钥与隐私
- 🔑 **专用钱包**: 不要使用主钱包私钥，创建专门的交易钱包
- 🚫 **严禁提交**: 永远不要将 `.env` 文件提交到版本控制
- 🔒 **权限控制**: `.env` 文件权限设置为 `chmod 600`
- 💾 **备份私钥**: 安全备份私钥，避免资金丢失

### 监控与维护
- 📝 **定期检查**: 查看日志和仓位状态，及时发现异常
- 📊 **使用监控面板**: 运行 `monitor_dashboard.py` 实时监控
- 🏥 **启用健康检查**: 配置 `health_check.py` 自动告警
- 🔔 **Telegram通知**: 启用通知及时了解交易状态

### 市场风险警示
⚠️ **重要提醒：**
- 跟单存在固有风险，Leader的交易不保证盈利
- 市场波动可能导致重大损失
- 本工具仅供学习和研究，不构成投资建议
- 使用前请充分了解风险，自行承担所有交易后果

## 📚 完整文档索引

### 🎯 新手必读
| 文档 | 说明 | 难度 |
|------|------|------|
| [QUICK_START.md](QUICK_START.md) | 5分钟快速上手指南 | ⭐ 入门 |
| [USAGE_CHECKLIST.md](USAGE_CHECKLIST.md) | 上线前完整检查清单 | ⭐ 入门 |
| [COPY_MODE_GUIDE.md](COPY_MODE_GUIDE.md) | Position vs Wallet 模式选择 | ⭐⭐ 基础 |
| [COPY_RATIO_GUIDE.md](COPY_RATIO_GUIDE.md) | 跟单比例计算详解 | ⭐⭐ 基础 |

### 🔧 配置与部署
| 文档 | 说明 | 难度 |
|------|------|------|
| [ENV_SETUP_GUIDE.md](ENV_SETUP_GUIDE.md) | 环境变量详细配置说明 | ⭐⭐ 基础 |
| [SELF_TRADING_GUIDE.md](SELF_TRADING_GUIDE.md) | 自己也在交易时的配置 | ⭐⭐ 基础 |
| [SERVER_DEPLOY_GUIDE.md](SERVER_DEPLOY_GUIDE.md) | 服务器部署与运维 | ⭐⭐⭐ 进阶 |

### 💼 多实例管理
| 文档 | 说明 | 难度 |
|------|------|------|
| [MULTI_WALLET_QUICK_START.md](MULTI_WALLET_QUICK_START.md) | 1分钟上手多钱包跟单 | ⭐⭐ 基础 |
| [MULTI_INSTANCE_GUIDE.md](MULTI_INSTANCE_GUIDE.md) | 多钱包多Leader完整配置 | ⭐⭐⭐ 进阶 |

### 🛠️ 运维与优化
| 文档 | 说明 | 难度 |
|------|------|------|
| [OPTIMIZATION_GUIDE.md](OPTIMIZATION_GUIDE.md) | 性能优化与运维工具 | ⭐⭐⭐ 进阶 |
| [OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md) | 优化变更总结 | ⭐⭐⭐ 进阶 |

### 👨‍💻 开发者文档
| 文档 | 说明 | 难度 |
|------|------|------|
| [AI_HANDOFF_PROMPT.md](AI_HANDOFF_PROMPT.md) | 项目架构与开发者接手 | ⭐⭐⭐⭐ 专家 |

---

## 📁 项目结构

```
copybot/
├── src/                          # 核心源代码 (6791行)
│   ├── copy_trader.py           # 主程序入口 (1735行)
│   ├── trade_monitor.py         # REST API交易监控 (325行)
│   ├── websocket_monitor.py     # WebSocket实时监控 (533行)
│   ├── position_manager.py      # 仓位管理与执行 (1646行)
│   ├── trade_batcher.py         # 交易批处理器 (198行)
│   ├── notifications/
│   │   └── telegram.py          # Telegram通知服务
│   └── utils/
│       ├── helpers.py           # 配置加载与辅助工具
│       └── smart_logger.py      # 智能日志过滤
│
├── scripts/                      # 运维和工具脚本 (14个)
│   ├── run_copy_trader.py       # 单实例启动器
│   ├── run_multi_trader.py      # 多实例启动器
│   ├── manage_copy_trader.sh    # 单实例管理菜单
│   ├── manage_multi_trader.sh   # 多实例管理菜单
│   ├── deploy_update.sh         # 一键部署更新
│   ├── health_check.py          # 健康检查告警
│   ├── monitor_dashboard.py     # 实时监控面板
│   ├── trading_report.py        # 交易统计报表
│   ├── sync_positions.py        # 仓位纠偏工具
│   ├── validate_env.sh          # 环境变量验证
│   ├── check_config.sh          # 配置检查
│   ├── clean_old_logs.py        # 日志清理
│   └── test_telegram.py         # Telegram测试
│
├── config/                       # 配置文件
│   ├── config.yaml              # 单实例配置模板
│   └── multi_config.yaml        # 多实例配置模板
│
├── docs/                         # 文档目录 (13份)
│   └── (见上方文档索引)
│
├── .env.example                  # 环境变量示例
├── .env.template                 # 详细环境变量模板
├── requirements.txt              # Python依赖
└── README.md                     # 本文件
```

---

## 🤝 贡献与支持

### 问题反馈
如果遇到问题或有改进建议，欢迎：
- 📝 提交 Issue
- 💡 提出 Feature Request
- 🐛 报告 Bug

### 开发贡献
欢迎提交 Pull Request！请确保：
- ✅ 代码符合项目风格
- ✅ 添加必要的测试
- ✅ 更新相关文档

---

## 📜 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

## ⚖️ 免责声明

**重要提醒：**
- 本软件仅供学习和研究使用
- 使用本软件进行交易存在重大风险，包括但不限于全部资金损失
- 作者不对使用本软件造成的任何直接或间接损失承担责任
- 请在充分了解风险、遵守当地法律法规的前提下使用
- 加密货币交易具有高风险，不适合所有投资者
- 过往业绩不代表未来表现

**使用本软件即表示您已理解并同意上述条款。**

---

## 📞 联系方式

- GitHub Issues: [提交问题](https://github.com/yourusername/copybot/issues)
- 文档维护: 查看 [AI_HANDOFF_PROMPT.md](AI_HANDOFF_PROMPT.md) 了解项目架构

---

**⭐ 如果这个项目对您有帮助，欢迎给个 Star！**
