# 多钱包多Leader跟单指南

## 功能介绍

多实例跟单功能允许你使用不同的钱包同时跟踪多个leader的交易，每个实例完全独立运行，互不干扰。

### 特性

- ✅ **多钱包支持** - 每个实例使用独立的follower钱包
- ✅ **多Leader跟踪** - 同时跟踪多个不同的leader地址
- ✅ **独立配置** - 每个实例有独立的跟单比例、风控参数等
- ✅ **进程隔离** - 使用多进程架构，一个实例崩溃不影响其他
- ✅ **独立日志** - 每个实例有独立的日志文件
- ✅ **自动重启** - 监控模式下自动检测并重启崩溃的实例
- ✅ **灵活管理** - 可以单独启动/停止任意实例

## 快速开始

### 1. 配置文件

复制并编辑配置文件：

```bash
cp config/multi_config.yaml config/my_multi_config.yaml
nano config/my_multi_config.yaml
```

配置示例：

```yaml
# 全局配置
global_settings:
  use_testnet: false
  logging:
    level: INFO
    base_dir: logs
  telegram:
    enabled: true
    bot_token: "your_bot_token"
    chat_id: "your_chat_id"

# 跟单实例列表
trading_instances:
  # 实例1: 跟踪Leader A
  - name: "trader_1"
    enabled: true
    target_address: "0xLeaderA..."
    exclude_addresses:
      - "0xYourFollowerAddress1"
    hyperliquid:
      account_address: "0xYourFollowerAddress1"
      private_key: "0xYourPrivateKey1"
    copy_trading:
      copy_ratio: 0.1  # 10%
      max_position_size: 10.0
    
  # 实例2: 跟踪Leader B
  - name: "trader_2"
    enabled: true
    target_address: "0xLeaderB..."
    exclude_addresses:
      - "0xYourFollowerAddress2"
    hyperliquid:
      account_address: "0xYourFollowerAddress2"
      private_key: "0xYourPrivateKey2"
    copy_trading:
      copy_ratio: 0.2  # 20%
      max_position_size: 20.0
```

### 2. 启动方式

#### 方式1: 使用管理脚本（推荐）

```bash
# 交互式菜单
./scripts/manage_multi_trader.sh

# 直接命令
./scripts/manage_multi_trader.sh start   # 启动所有
./scripts/manage_multi_trader.sh stop    # 停止所有
./scripts/manage_multi_trader.sh status  # 查看状态
./scripts/manage_multi_trader.sh monitor # 监控模式
```

#### 方式2: 使用Python脚本

```bash
# 启动所有启用的实例
python scripts/run_multi_trader.py start

# 停止所有实例
python scripts/run_multi_trader.py stop

# 查看状态
python scripts/run_multi_trader.py status

# 监控模式（自动重启）
python scripts/run_multi_trader.py monitor

# 启动单个实例
python scripts/run_multi_trader.py start --instance trader_1

# 停止单个实例
python scripts/run_multi_trader.py stop --instance trader_1

# 使用自定义配置文件
python scripts/run_multi_trader.py start --config config/my_multi_config.yaml
```

### 3. 查看日志

每个实例都有独立的日志文件：

```bash
# 查看trader_1的日志
tail -f logs/trader_1.log

# 查看所有实例的日志
tail -f logs/trader_*.log

# 查看最近50行
tail -50 logs/trader_1.log
```

## 配置说明

### 全局配置

```yaml
global_settings:
  # 是否使用测试网（所有实例共享）
  use_testnet: false
  
  # 日志配置
  logging:
    level: INFO          # 日志级别: DEBUG, INFO, WARNING, ERROR
    base_dir: logs       # 日志目录
  
  # Telegram通知（所有实例共享同一个bot）
  telegram:
    enabled: true
    bot_token: "your_token"
    chat_id: "your_chat_id"
```

### 实例配置

每个实例包含以下配置：

```yaml
- name: "trader_1"           # 实例名称（必须唯一）
  enabled: true              # 是否启用此实例
  
  # Leader配置
  target_address: "0x..."    # 要跟踪的leader地址
  exclude_addresses:         # 排除地址列表
    - "0x..."
  
  # Follower钱包配置
  hyperliquid:
    account_address: "0x..." # follower钱包地址
    private_key: "0x..."     # follower钱包私钥
    vault_address: ""        # 金库地址（可选）
  
  # 跟单参数
  copy_trading:
    copy_ratio: 0.1          # 跟单比例（0.1 = 10%）
    max_position_size: 10.0  # 单币种最大仓位
    min_trade_size: 0.01     # 最小交易大小
    max_leverage: 5          # 最大杠杆
  
  # 风险控制
  risk_management:
    max_drawdown: 0.1        # 最大回撤（10%）
    stop_loss_ratio: 0.05    # 止损比例（5%）
    take_profit_ratio: 0.1   # 止盈比例（10%）
  
  # 监控配置
  monitoring:
    poll_interval: 30        # 轮询间隔（秒）
    max_retries: 3           # 最大重试次数
    retry_delay: 5           # 重试延迟（秒）
```

## 高级用法

### 1. 监控模式

监控模式会持续运行并自动重启崩溃的实例：

```bash
python scripts/run_multi_trader.py monitor
```

特性：
- 每30秒检查一次所有实例状态
- 自动重启崩溃的实例
- 按Ctrl+C退出监控模式

### 2. 按需启动实例

可以只启动部分实例：

1. 在配置文件中设置 `enabled: false` 禁用不需要的实例
2. 或者使用 `--instance` 参数启动特定实例：

```bash
python scripts/run_multi_trader.py start --instance trader_1
```

### 3. 动态添加实例

1. 编辑配置文件添加新实例
2. 无需停止现有实例，直接启动新实例：

```bash
python scripts/run_multi_trader.py start --instance trader_3
```

### 4. 进程管理

查看所有运行中的实例：

```bash
ps aux | grep copybot
```

查看实例PID：

```bash
python scripts/run_multi_trader.py status
```

## 最佳实践

### 1. 资金管理

- 每个follower钱包独立管理资金
- 根据风险承受能力设置不同的跟单比例
- 建议从小比例开始测试（如0.01 = 1%）

### 2. 风险控制

- 为每个实例设置合适的止损止盈
- 监控各个钱包的账户余额
- 使用不同的钱包分散风险

### 3. 性能优化

- 不建议在单台服务器上运行过多实例（建议≤10个）
- 为重要的leader分配更多资源
- 定期检查日志文件大小

### 4. 日志管理

```bash
# 定期清理旧日志
find logs -name "trader_*.log" -mtime +7 -delete

# 或使用日志轮换
# 在multi_config.yaml中配置日志轮换策略
```

### 5. 监控建议

建议使用监控面板实时查看所有实例状态：

```bash
# 为每个实例创建监控
python scripts/monitor_dashboard.py --compact
```

## 故障排查

### 实例无法启动

1. 检查配置文件语法：
```bash
python -c "import yaml; yaml.safe_load(open('config/multi_config.yaml'))"
```

2. 检查日志文件：
```bash
tail -100 logs/trader_1.log
```

3. 检查钱包配置：
   - 确认私钥格式正确（以0x开头）
   - 确认地址正确
   - 确认账户有足够余额

### 实例频繁崩溃

1. 检查网络连接
2. 检查API限流（可能需要降低poll_interval）
3. 查看错误日志

### 配置文件错误

常见错误：
- YAML缩进错误（使用2个空格）
- 地址格式错误（必须以0x开头）
- 私钥格式错误
- 比例值错误（0-1之间）

## 安全建议

1. **私钥安全**
   - 不要将配置文件提交到git
   - 使用 `.gitignore` 排除配置文件
   - 定期更换私钥

2. **权限控制**
   ```bash
   chmod 600 config/multi_config.yaml  # 仅所有者可读写
   ```

3. **环境隔离**
   - 测试网和主网使用不同的配置文件
   - 生产环境使用专用服务器

4. **监控告警**
   - 启用Telegram通知
   - 设置止损告警
   - 监控账户余额

## 示例场景

### 场景1: 跟踪3个不同风格的trader

```yaml
trading_instances:
  # 保守型trader - 低杠杆，小仓位
  - name: "conservative_trader"
    target_address: "0xConservativeLeader..."
    copy_trading:
      copy_ratio: 0.05  # 5%
      max_leverage: 2
  
  # 平衡型trader - 中等参数
  - name: "balanced_trader"
    target_address: "0xBalancedLeader..."
    copy_trading:
      copy_ratio: 0.1   # 10%
      max_leverage: 3
  
  # 激进型trader - 高比例，严格止损
  - name: "aggressive_trader"
    target_address: "0xAggressiveLeader..."
    copy_trading:
      copy_ratio: 0.15  # 15%
      max_leverage: 5
    risk_management:
      stop_loss_ratio: 0.03  # 更严格的止损
```

### 场景2: 测试和生产环境分离

```yaml
# 测试配置
trading_instances:
  - name: "test_trader"
    enabled: true
    target_address: "0xTestLeader..."
    hyperliquid:
      account_address: "0xTestAccount..."
      # ... 测试网配置

# 生产配置（创建独立文件）
# config/production_multi_config.yaml
```

## 常见问题

**Q: 可以同时跟踪同一个leader吗？**  
A: 可以，但要使用不同的follower钱包。

**Q: 实例之间会相互影响吗？**  
A: 不会，每个实例是独立的进程。

**Q: 如何限制总资金使用量？**  
A: 通过设置每个钱包的余额和max_position_size来控制。

**Q: 可以在运行中修改配置吗？**  
A: 需要重启对应的实例才能应用新配置。

**Q: 如何备份配置？**  
A: 定期备份multi_config.yaml文件到安全位置。

## 相关文档

- [单实例快速开始](QUICK_START.md)
- [环境变量配置](ENV_SETUP_GUIDE.md)
- [服务器部署](SERVER_DEPLOY_GUIDE.md)
- [监控工具使用](OPTIMIZATION_GUIDE.md)
