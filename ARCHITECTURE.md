# Hyperliquid Copy Trader - 项目架构文档

![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-brightgreen.svg)

本文档详细说明项目的技术架构、核心模块、数据流和设计决策。

---

## 📐 总体架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     Hyperliquid Copy Trader                     │
│                         (Main Process)                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ├──────────────────────────────┐
                              │                              │
                    ┌─────────▼─────────┐          ┌────────▼────────┐
                    │  Trade Monitor    │          │  WebSocket      │
                    │  (REST Polling)   │          │  Monitor        │
                    └─────────┬─────────┘          └────────┬────────┘
                              │                              │
                              └──────────┬───────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Trade Dedup &      │
                              │  Batch Processing   │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Position Manager   │
                              │  (Order Execution)  │
                              └──────────┬──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
          ┌─────────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
          │  Hyperliquid     │  │  Telegram      │  │  Position      │
          │  Exchange API    │  │  Notification  │  │  Sync Loop     │
          └──────────────────┘  └────────────────┘  └────────────────┘
```

---

## 🧩 核心模块

### 1. HyperliquidCopyTrader (copy_trader.py)

**职责：** 主程序入口，协调所有子模块

**核心功能：**
- 配置加载和环境变量解析
- 初始化所有子模块（monitor, position_manager, notifier）
- 管理异步事件循环和任务
- 信号处理（SIGINT/SIGTERM优雅关闭）
- 中心化交易去重（`_processed_tx_hashes`）

**关键方法：**
```python
__init__(config_path, config_dict)          # 初始化
start()                                     # 启动主循环
stop()                                      # 优雅停止
_websocket_monitoring_loop()                # WebSocket监控循环
_rest_monitoring_loop()                     # REST轮询循环
_position_sync_loop()                       # 仓位同步循环
_catch_up_missed_trades_strict_better()     # 断线补单
_handle_trade_batch(trades)                 # 批处理交易
```

**数据结构：**
- `_processed_tx_hashes: set[str]` - 已处理交易哈希
- `_processed_tx_order: deque[str]` - 交易哈希顺序队列
- `_inflight_tx_hashes: set[str]` - 正在处理的交易
- `_dedup_lock: asyncio.Lock` - 去重锁

**配置加载优先级：**
1. 环境变量（`.env` 文件）
2. YAML 配置文件（`config.yaml`）
3. 代码中的默认值

---

### 2. TradeMonitor (trade_monitor.py)

**职责：** 通过 REST API 轮询监控 Leader 交易历史

**核心功能：**
- 定期调用 `info.user_fills(address)` 获取交易历史
- 解析 `fills` 数据，转换为 `MonitoredTrade` 对象
- 实现智能缓存（500ms 缓存 + 2秒强制刷新）
- 处理 429 速率限制（指数退避）

**关键方法：**
```python
get_recent_trades()                         # 获取最近交易（带缓存）
_parse_user_fills(fills)                    # 解析交易数据
_apply_rate_limit(current_time)             # 速率限制
```

**数据结构：**
```python
class MonitoredTrade:
    action: TradeAction        # OPEN_LONG, CLOSE_SHORT 等
    coin: str                  # 交易币种
    size: float                # 数量
    price: float               # 价格
    leverage: int              # 杠杆
    timestamp: int             # 时间戳（毫秒）
    tx_hash: str               # 交易哈希
```

**缓存策略：**
- 最小缓存时间：500ms
- 强制刷新间隔：2秒
- 避免短时间内重复 API 调用

**429 处理：**
- 初始退避：5秒
- 最大退避：300秒（5分钟）
- 指数增长因子：2

---

### 3. WebSocketMonitor (websocket_monitor.py)

**职责：** 通过 WebSocket 实时接收 Leader 的交易 fills

**核心功能：**
- 订阅 Leader 地址的实时 fills
- 心跳检测和自动重连
- 空闲超时处理
- 与 REST monitor 共享去重机制

**关键方法：**
```python
start()                                     # 启动 WebSocket 连接
stop()                                      # 关闭连接
_on_fills_callback(fills)                   # fills 回调处理
_heartbeat_loop()                           # 心跳和重连逻辑
```

**重连策略：**
- 空闲超时：30秒无消息自动重连
- 日志节流：300秒内只输出一次重连 warning
- 断线后自动触发 catchup 补单

**与 REST 的配合：**
- WebSocket 优先（低延迟）
- REST 作为备份（轮询间隔30秒）
- 共享 `_processed_tx_hashes` 避免重复

---

### 4. PositionManager (position_manager.py)

**职责：** 执行交易订单和仓位管理

**核心功能：**
- 执行开仓、平仓、杠杆调整
- 仓位同步纠偏
- 风控检查（最大仓位、止损等）
- 处理交易所精度限制（`szDecimals`）

**关键方法：**
```python
execute_copy_trade(trade)                   # 执行单笔跟单
execute_position_sync(sync_orders)          # 执行仓位纠偏
update_positions()                          # 更新仓位缓存
_get_account_value_usd()                    # 获取账户价值
_check_stop_loss()                          # 检查止损
```

**数据结构：**
```python
class Position:
    coin: str                  # 币种
    size: float                # 仓位大小（正=多，负=空）
    entry_price: float         # 开仓均价
    leverage: int              # 杠杆
    unrealized_pnl: float      # 未实现盈亏

class SyncOrder:
    coin: str                  # 币种
    kind: str                  # open/close/increase/reduce
    size: float                # 数量
    price: float               # 价格
    notional: float            # 名义金额
    reason: str                # 纠偏原因
```

**风控机制：**
1. **最大仓位检查**：`MAX_POSITION_SIZE`
2. **最大杠杆限制**：`MAX_LEVERAGE`
3. **止损检查**：`STOP_LOSS_RATIO`
4. **最小订单金额**：`MIN_ORDER_NOTIONAL_USD` (≥10 USD)

**翻仓安全模式** (`FLIP_WAIT_FOR_CLOSE=true`)：
1. 提交反向仓位的 `market_close`
2. 轮询 `user_state` 直到对侧仓位消失
3. 仓位确认消失后，提交新方向的 `market_open`

**精度处理：**
- 从 `info.meta()` 获取每个币种的 `szDecimals`
- 按精度向下取整（truncate）订单大小
- 缓存 meta 数据（TTL=600秒）

---

### 5. TradeBatcher (trade_batcher.py)

**职责：** 聚合高频交易，减少 API 调用和订单拥挤

**核心功能：**
- 时间窗口内聚合同币种同方向交易
- 按优先级排序（CLOSE > OPEN）
- 自动累加 sizes 和选择最大杠杆

**关键方法：**
```python
submit(trade)                               # 提交交易（非阻塞）
get_stats()                                 # 获取统计信息
_aggregate(trades)                          # 聚合交易
```

**聚合规则：**
- **时间窗口**：`TRADE_BATCH_WINDOW_MS`（默认500ms）
- **分组键**：`(coin, action)`
- **优先级**：CLOSE 操作优于 OPEN（避免翻仓冲突）
- **Netting**：同方向 sizes 累加

**示例：**
```
输入（100ms 内）：
  - OPEN_LONG BTC 0.1
  - OPEN_LONG BTC 0.05
  - CLOSE_SHORT ETH 1.0

输出（批处理后）：
  1. CLOSE_SHORT ETH 1.0 (优先级高)
  2. OPEN_LONG BTC 0.15    (聚合)
```

---

### 6. NotificationManager (notifications/telegram.py)

**职责：** Telegram 通知和交互式确认

**核心功能：**
- 发送交易通知（开仓、平仓、失败）
- 启动摘要和状态报告
- 双步确认（catchup 补单）
- 通知节流（避免刷屏）

**关键方法：**
```python
send_trade_notification(trade, result)      # 交易通知
send_startup_summary(config)                # 启动摘要
send_position_snapshot(positions)           # 仓位快照
ask_for_approval(message, timeout)          # 交互式确认
```

**节流机制：**
- 跳过交易通知：`TELEGRAM_SKIPPED_TRADE_THROTTLE_S`（默认300秒）
- 同一币种同一原因在窗口内只发一次汇总

**Markdown 格式：**
- 支持加粗、代码块、列表
- 自动转义特殊字符
- 错误处理（降级为纯文本）

---

## 🔄 数据流

### 交易执行流程

```
┌─────────────┐
│  Leader     │ 交易
│  执行交易    │────────┐
└─────────────┘        │
                       │
                       ▼
         ┌─────────────────────────┐
         │  WebSocket / REST API   │ 检测交易
         └─────────┬───────────────┘
                   │
                   ▼
         ┌─────────────────────────┐
         │  Trade Deduplication    │ 去重
         │  (_processed_tx_hashes) │
         └─────────┬───────────────┘
                   │
                   ▼
         ┌─────────────────────────┐
         │  Trade Batcher          │ 批处理
         │  (聚合高频交易)           │
         └─────────┬───────────────┘
                   │
                   ▼
         ┌─────────────────────────┐
         │  Position Manager       │ 风控检查
         │  (风控 + 精度处理)        │
         └─────────┬───────────────┘
                   │
                   ▼
         ┌─────────────────────────┐
         │  Hyperliquid Exchange   │ 下单
         │  (market_open/close)    │
         └─────────┬───────────────┘
                   │
                   ▼
         ┌─────────────────────────┐
         │  Telegram Notification  │ 通知
         └─────────────────────────┘
```

### 仓位同步流程

```
┌─────────────────┐
│  Position Sync  │ 定时触发（默认300秒）
│  Loop           │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  获取 Leader 仓位        │
│  获取 Follower 仓位      │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  计算期望仓位            │
│  (Leader * copy_ratio)  │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  计算差异 (delta)        │
│  过滤小差异 (< 5%)       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  价格门控检查            │
│  (strict_fill_open)     │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  生成 SyncOrder         │
│  执行纠偏订单            │
└─────────────────────────┘
```

---

## 🛡️ 安全机制

### 1. 交易去重

**问题：** WebSocket 和 REST 可能收到同一笔交易

**解决方案：**
- 中心化去重：所有 monitor 共享 `_processed_tx_hashes`
- 使用交易哈希 (`tx_hash`) 作为唯一标识
- 双检查锁：`async with _dedup_lock`

**自动清理：**
- 保留最近 10000 条记录
- 超过时自动清理最旧的 1000 条

### 2. 翻仓安全

**问题：** 直接提交反向订单可能导致净头寸错误

**解决方案：**
- `FLIP_WAIT_FOR_CLOSE=true`：先平后开
- 轮询确认对侧仓位完全消失
- 超时保护（默认6秒）

### 3. 仓位纠偏门控

**价格门控** (`POSITION_SYNC_PRICE_REF_MODE=strict_fill_open`)：
- 使用 Leader 最近 OPEN 价格作为基准
- 当前 mid 价格必须严格优于基准价
- 避免在不利价格追单

**点差门控** (`POSITION_SYNC_SPREAD_GATE_ENABLED`)：
- 超宽点差时跳过纠偏
- 保护资金避免滑点损失

**时间门控** (`POSITION_SYNC_SKIP_RECENT_TRADE_S`)：
- Leader 刚成交30秒内不纠偏该币种
- 避免与实时跟单打架

### 4. 手动干预保护

**手动平仓检测：**
- 连续 N 次检查仓位消失（`POSITION_SYNC_MANUAL_CONFIRMATIONS=2`）
- 进入冷却期，不自动重建仓位

**锁定模式** (`POSITION_SYNC_MANUAL_LOCK_UNTIL_LEADER_FLAT=true`)：
- 手动平仓后，直到 Leader 也平仓才解除锁定
- 防止误判和意外重建

---

## ⚙️ 配置系统

### 配置优先级

```
环境变量 (.env)
    ↓
YAML 配置文件 (config.yaml)
    ↓
代码默认值
```

### 关键配置类别

**1. 跟单模式 (v1.5.0)**
- `COPY_MODE`: position / wallet
- `COPY_RATIO`: 固定比例（position 模式）

**2. 监控配置**
- `USE_WEBSOCKET`: 启用 WebSocket
- `WEBSOCKET_IDLE_TIMEOUT_S`: 空闲超时
- `TRADE_BATCH_WINDOW_MS`: 批处理窗口

**3. 断线恢复**
- `CATCHUP_ENABLED`: 启用补单
- `CATCHUP_REPLAY_OPENS`: 是否回放 OPEN（默认 false）
- `CATCHUP_WINDOW_S`: 回溯时间窗口

**4. 仓位同步**
- `POSITION_SYNC_ENABLED`: 启用纠偏
- `POSITION_SYNC_PRICE_REF_MODE`: 价格门控模式
- `POSITION_SYNC_SPREAD_GATE_ENABLED`: 点差门控

**5. 风险管理**
- `MAX_POSITION_SIZE`: 最大仓位
- `MAX_NOTIONAL_PER_TRADE_USD`: 单笔限额
- `STOP_LOSS_RATIO`: 止损比例
- `FLIP_WAIT_FOR_CLOSE`: 翻仓安全模式

---

## 🔌 依赖关系

### 核心依赖

```python
hyperliquid-python-sdk>=0.1.0      # Hyperliquid 官方 SDK
python-dotenv>=1.0.0               # 环境变量加载
pyyaml>=6.0                        # YAML 配置解析
websockets>=12.0                   # WebSocket 客户端
aiohttp>=3.9.0                     # 异步 HTTP
eth-account>=0.8.0                 # 以太坊签名
pydantic>=2.0.0                    # 数据验证
```

### SDK API 使用

**Info（查询）：**
```python
from hyperliquid.info import Info
info = Info(constants.MAINNET_API_URL, skip_ws=True)
user_state = info.user_state(address)
user_fills = info.user_fills(address)
meta = info.meta()
```

**Exchange（交易）：**
```python
from hyperliquid.exchange import Exchange
exchange = Exchange(wallet, base_url=constants.MAINNET_API_URL)
result = exchange.market_open(coin, is_buy, sz)
result = exchange.market_close(coin)
result = exchange.update_leverage(leverage, coin)
```

---

## 📊 性能优化

### 1. 缓存策略

**Meta 数据缓存：**
- TTL: 600秒
- 包含：`szDecimals`、`maxLeverage` 等

**仓位缓存：**
- 本地维护仓位快照
- 避免频繁调用 `user_state`

**交易历史缓存：**
- 500ms 最小缓存
- 2秒强制刷新

### 2. 批处理

**Trade Batcher：**
- 减少 API 调用次数
- 降低 429 限制风险
- 窗口可配置（默认500ms）

### 3. 速率限制

**指数退避：**
- 429 错误时自动退避
- 最大退避：300秒
- 成功后重置

**API 间隔：**
- 最小间隔：`MIN_API_INTERVAL`（默认1000ms）
- 防止过度请求

---

## 🔍 日志与监控

### 日志系统

**SmartLogFilter：**
- 自动节流重复日志
- 减少噪音，提高可读性

**日志级别：**
- DEBUG: 详细调试信息
- INFO: 正常操作日志
- WARNING: 警告（如重连、跳过）
- ERROR: 错误和异常

**日志轮换：**
- 按天自动轮换
- 保留7天
- 自动清理旧日志

### 监控工具

**monitor_dashboard.py：**
- 实时仓位显示
- P&L 统计
- 比例准确度

**health_check.py：**
- 进程健康检查
- API 连接测试
- Telegram 告警

**trading_report.py：**
- 日/周/月报
- 成功率统计
- 币种分布分析

---

## 🧪 测试策略

### 单元测试

位置：`tests/`

覆盖模块：
- `test_trade_monitor.py`: 交易监控
- `test_position_manager.py`: 仓位管理
- `test_trade_batcher.py`: 批处理

运行：
```bash
python -m pytest tests/ -v
```

### 集成测试

位置：根目录

测试脚本：
- `test_trading.py`: 交易执行测试
- `test_websocket.py`: WebSocket 连接测试
- `test_telegram.py`: Telegram 通知测试

---

## 🚀 部署架构

### 单实例部署

```
┌─────────────────────┐
│   Linux Server      │
│  ┌───────────────┐  │
│  │  Copy Trader  │  │
│  │  (1 Process)  │  │
│  └───────────────┘  │
│         │           │
│         ▼           │
│  ┌───────────────┐  │
│  │  logs/        │  │
│  │  .env         │  │
│  └───────────────┘  │
└─────────────────────┘
```

管理脚本：`manage_copy_trader.sh`

### 多实例部署

```
┌─────────────────────────────┐
│      Linux Server           │
│  ┌─────────┐  ┌─────────┐  │
│  │ Trader1 │  │ Trader2 │  │
│  │ Leader1 │  │ Leader2 │  │
│  └─────────┘  └─────────┘  │
│       │            │        │
│       ▼            ▼        │
│  ┌─────────────────────┐   │
│  │  logs/              │   │
│  │   ├─ trader1.log    │   │
│  │   └─ trader2.log    │   │
│  └─────────────────────┘   │
└─────────────────────────────┘
```

管理脚本：`manage_multi_trader.sh`

配置：
- `config/multi_config.yaml`：实例定义
- `.env`：私钥按实例名映射
  - `HYPERLIQUID_PRIVATE_KEY_TRADER1=...`
  - `HYPERLIQUID_PRIVATE_KEY_TRADER2=...`

---

## 🔐 安全考虑

### 1. 私钥管理

**存储：**
- 使用环境变量（`.env`）
- 权限控制：`chmod 600 .env`
- 永不提交到版本控制

**多实例：**
- 按实例名分离私钥
- 环境变量命名规则：`HYPERLIQUID_PRIVATE_KEY_{INSTANCE_NAME}`

### 2. API 密钥

**Telegram：**
- Bot Token 存储在环境变量
- Chat ID 校验

### 3. 网络安全

**HTTPS Only：**
- 所有 API 调用使用 HTTPS
- WebSocket 使用 WSS（TLS）

**错误处理：**
- 不在日志中暴露私钥
- 敏感信息脱敏

---

## 📝 代码规范

### Python 风格

**遵循 PEP 8：**
- 缩进：4空格
- 行长：≤120字符
- 命名：snake_case

**类型注解：**
```python
def execute_copy_trade(self, trade: MonitoredTrade) -> bool:
    ...
```

**Docstring：**
```python
def get_recent_trades(self) -> List[MonitoredTrade]:
    """获取最近的交易。

    Returns:
        MonitoredTrade 对象列表
    """
    ...
```

### 异步编程

**使用 asyncio：**
- 所有 IO 操作异步化
- 使用 `async def` 和 `await`
- 任务管理：`asyncio.create_task()`

**错误处理：**
```python
try:
    result = await some_async_call()
except Exception as e:
    logger.error(f"Error: {e}")
    # 优雅降级
```

---

## 🔄 版本演进

### v1.0.0 - 基础版本
- REST API 监控
- 基本跟单功能
- Telegram 通知

### v1.1.0 - 运维工具
- 监控面板
- 交易报表
- 健康检查
- 一键部署

### v1.2.0 - 性能优化
- WebSocket 监控
- 交易批处理
- 仓位同步
- 断线补单

### v1.3.0 - 日志管理
- 日志轮换
- 自动清理
- SmartLogFilter

### v1.4.0 - 多实例
- 多钱包支持
- 多 Leader 跟单
- 进程隔离

### v1.5.0 - 双模式 (当前)
- Position 模式（固定比例）
- Wallet 模式（动态比例）
- 改进文档

---

## 📚 相关文档

- [README.md](README.md) - 项目总览
- [AI_HANDOFF_PROMPT.md](AI_HANDOFF_PROMPT.md) - 开发者接手文档
- [OPTIMIZATION_GUIDE.md](OPTIMIZATION_GUIDE.md) - 性能优化指南
- [ENV_SETUP_GUIDE.md](ENV_SETUP_GUIDE.md) - 配置说明

---

**文档版本：** 1.5.0
**最后更新：** 2026-01-01
**维护者：** Copybot Team
