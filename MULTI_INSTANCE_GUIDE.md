# 多钱包多Leader跟单使用指南

## 功能介绍

多实例跟单功能允许你**同时使用不同的钱包跟踪多个Leader**，每个实例完全独立运行，互不干扰。

### 典型使用场景

**场景1：跟踪多个不同的Leader**
- 钱包A跟踪Leader_1（高频短线）
- 钱包B跟踪Leader_2（中长线）
- 钱包C跟踪Leader_3（套利策略）

**场景2：同一Leader不同策略**
- 钱包A：10%比例，激进策略
- 钱包B：5%比例，保守策略
- 钱包C：Wallet模式，自动调整

**场景3：风险分散**
- 分散资金到多个钱包
- 每个钱包独立止损
- 降低单点风险

### 核心特性

- ✅ **多钱包** - 每个实例使用独立的Follower钱包
- ✅ **多Leader** - 同时跟踪多个不同的Leader地址
- ✅ **独立配置** - 每个实例有独立的跟单比例、模式、风控参数
- ✅ **进程隔离** - 一个实例崩溃不影响其他实例
- ✅ **独立日志** - 每个实例有独立的日志文件，便于追踪
- ✅ **自动重启** - 监控模式下自动检测并重启崩溃的实例
- ✅ **灵活管理** - 可以单独启动/停止/重启任意实例
- ✅ **双模式支持** - 每个实例可选Position或Wallet模式

---

## 快速开始（3步上手）

### 第1步：准备配置文件

```bash
# 复制配置模板
cp config/multi_config.yaml config/my_multi.yaml

# 编辑配置文件
nano config/my_multi.yaml
```

**最简配置示例：**

```yaml
global_settings:
  use_testnet: false  # 使用主网

trading_instances:
  # 实例1
  - name: "trader_1"
    enabled: true
    target_address: "0xLeaderAddress1..."  # Leader地址
    
    hyperliquid:
      account_address: "0xYourAddress1..."  # 你的钱包1
      private_key: "__FROM_ENV__"           # 从 .env 读取（HYPERLIQUID_PRIVATE_KEY_TRADER_1）
    
    copy_trading:
      copy_mode: "position"  # 固定比例模式
      copy_ratio: 0.1        # 10%跟单
      max_position_size: 5.0
      max_leverage: 5

  # 实例2
  - name: "trader_2"
    enabled: true
    target_address: "0xLeaderAddress2..."  # 另一个Leader
    
    hyperliquid:
      account_address: "0xYourAddress2..."  # 你的钱包2
      private_key: "__FROM_ENV__"           # 从 .env 读取（HYPERLIQUID_PRIVATE_KEY_TRADER_2）
    
    copy_trading:
      copy_mode: "wallet"    # 钱包比例模式
      copy_ratio: 0.1        # 备用值
      max_position_size: 10.0
      max_leverage: 3
```

### 第2步：启动实例

**使用管理脚本（推荐新手）：**

```bash
# 进入交互式菜单
./scripts/manage_multi_trader.sh

# 选择 "1) Start all instances"
```

**或使用命令行：**

```bash
# 启动所有实例
python scripts/run_multi_trader.py start --config config/my_multi.yaml

# 启动单个实例
python scripts/run_multi_trader.py start --instance trader_1 --config config/my_multi.yaml
```

### 第3步：查看状态

```bash
# 查看所有实例状态
python scripts/run_multi_trader.py status --config config/my_multi.yaml

# 查看实时日志
tail -f logs/trader_1.log
```

**预期输出：**
```
Multi-Instance Status Report
═══════════════════════════════════════════

Instance: trader_1
  Status: ✅ RUNNING (PID: 12345)
  Leader: 0xLeader1...
  Follower: 0xYour1...
  Mode: position
  Log: logs/trader_1.log

Instance: trader_2
  Status: ✅ RUNNING (PID: 12346)
  Leader: 0xLeader2...
  Follower: 0xYour2...
  Mode: wallet
  Log: logs/trader_2.log
```

---

## 完整配置示例

### 场景1：跟踪3个不同的Leader

```yaml
global_settings:
  use_testnet: false
  logging:
    level: INFO
  telegram:
    enabled: true
    bot_token: "123456:ABC..."
    chat_id: "987654321"

trading_instances:
  # 跟踪Leader_1 - 激进策略
  - name: "aggressive_trader"
    enabled: true
    target_address: "0x1234...LeaderA"
    
    hyperliquid:
      account_address: "0xABCD...WalletA"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.2         # 20%激进跟单
      max_position_size: 20.0
      max_leverage: 10
      min_trade_size: 0.01

  # 跟踪Leader_2 - 保守策略  
  - name: "conservative_trader"
    enabled: true
    target_address: "0x5678...LeaderB"
    
    hyperliquid:
      account_address: "0xEFGH...WalletB"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "wallet"     # 钱包比例自动调整
      copy_ratio: 0.1
      max_position_size: 5.0
      max_leverage: 3
      max_notional_per_trade_usd: 1000

  # 跟踪Leader_3 - 测试策略
  - name: "test_trader"
    enabled: false            # 暂不启用
    target_address: "0x9ABC...LeaderC"
    
    hyperliquid:
      account_address: "0xIJKL...WalletC"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.05        # 5%小额测试
      max_position_size: 1.0
      max_leverage: 5
```

### 场景2：同一Leader，不同钱包不同策略

```yaml
trading_instances:
  # 同一Leader - 策略1：激进
  - name: "same_leader_aggressive"
    enabled: true
    target_address: "0xSAME_LEADER_ADDRESS"  # 相同Leader
    
    hyperliquid:
      account_address: "0xWALLET_1"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.2         # 20%
      max_position_size: 30.0
      max_leverage: 10
    
    risk_management:
      max_drawdown: 0.2       # 20%止损
      stop_loss_ratio: 0.1

  # 同一Leader - 策略2：保守
  - name: "same_leader_conservative"
    enabled: true
    target_address: "0xSAME_LEADER_ADDRESS"  # 相同Leader
    
    hyperliquid:
      account_address: "0xWALLET_2"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.05        # 5%
      max_position_size: 5.0
      max_leverage: 3
    
    risk_management:
      max_drawdown: 0.1       # 10%止损
      stop_loss_ratio: 0.05
```

---

## 管理命令详解

### 方式1：交互式管理脚本（推荐）

```bash
./scripts/manage_multi_trader.sh
```

**菜单选项：**
```
╔════════════════════════════════════════╗
║   Multi-Instance Copy Trader Manager   ║
╚════════════════════════════════════════╝

1) Start all instances      - 启动所有实例
2) Stop all instances       - 停止所有实例
3) Restart all instances    - 重启所有实例
4) Check status            - 查看状态
5) Monitor mode            - 监控模式（自动重启）
6) View logs              - 查看日志
7) Edit config            - 编辑配置
8) Exit                   - 退出

选择操作 [1-8]:
```

### 方式2：Python命令行

**基本命令：**

```bash
# 启动所有实例
python scripts/run_multi_trader.py start

# 停止所有实例
python scripts/run_multi_trader.py stop

# 重启所有实例
python scripts/run_multi_trader.py restart

# 查看状态
python scripts/run_multi_trader.py status

# 监控模式（自动重启崩溃的实例）
python scripts/run_multi_trader.py monitor
```

**单个实例管理：**

```bash
# 启动单个实例
python scripts/run_multi_trader.py start --instance trader_1

# 停止单个实例
python scripts/run_multi_trader.py stop --instance trader_2

# 重启单个实例
python scripts/run_multi_trader.py restart --instance trader_1

# 查看单个实例状态
python scripts/run_multi_trader.py status --instance trader_1
```

**使用自定义配置：**

```bash
# 指定配置文件
python scripts/run_multi_trader.py start --config config/my_multi.yaml

# 启动单个实例并指定配置
python scripts/run_multi_trader.py start --instance trader_1 --config config/my_multi.yaml
```

---

## 日志管理

### 日志文件位置

每个实例有独立的日志文件：

```
logs/
├── trader_1.log          # 实例1的日志
├── trader_2.log          # 实例2的日志
├── trader_3.log          # 实例3的日志
└── multi_trader.log      # 管理器日志
```

### 查看日志命令

```bash
# 实时查看单个实例日志
tail -f logs/trader_1.log

# 实时查看所有实例日志
tail -f logs/trader_*.log

# 查看最近100行
tail -100 logs/trader_1.log

# 搜索错误日志
grep -i error logs/trader_1.log

# 搜索交易日志
grep "Trade" logs/trader_1.log

# 查看今天的日志
grep "$(date +%Y-%m-%d)" logs/trader_1.log
```

### 日志级别

在配置文件中设置：

```yaml
global_settings:
  logging:
    level: INFO  # DEBUG, INFO, WARNING, ERROR
```

- **DEBUG**: 最详细，包含所有调试信息
- **INFO**: 正常运行信息，推荐日常使用
- **WARNING**: 警告信息
- **ERROR**: 仅错误信息

---

## 监控模式（推荐生产环境）

监控模式会自动检测实例状态，崩溃时自动重启。

### 启动监控模式

```bash
# 方式1：交互式菜单
./scripts/manage_multi_trader.sh
# 选择 "5) Monitor mode"

# 方式2：直接命令
python scripts/run_multi_trader.py monitor

# 指定配置文件
python scripts/run_multi_trader.py monitor --config config/my_multi.yaml
```

### 监控模式特性

- ✅ 每30秒检查一次所有实例状态
- ✅ 发现崩溃自动重启
- ✅ 记录重启次数和时间
- ✅ 可以Ctrl+C安全退出
- ✅ 退出时自动停止所有实例

### 后台运行监控模式

```bash
# 使用nohup后台运行
nohup python scripts/run_multi_trader.py monitor > monitor.log 2>&1 &

# 查看监控日志
tail -f monitor.log

# 停止监控（先找到进程ID）
ps aux | grep run_multi_trader
kill <PID>
```

---

## 常见问题与解决

### Q1: 如何添加新的实例？

**步骤：**

1. 编辑配置文件：
```bash
nano config/my_multi.yaml
```

2. 在`trading_instances`下添加新实例：
```yaml
- name: "new_trader"
  enabled: true
  target_address: "0xNewLeader..."
  hyperliquid:
    account_address: "0xNewWallet..."
    private_key: "__FROM_ENV__"
  copy_trading:
    copy_mode: "position"
    copy_ratio: 0.1
    max_position_size: 5.0
```

3. 重启所有实例或启动新实例：
```bash
# 方式1：启动新实例
python scripts/run_multi_trader.py start --instance new_trader

# 方式2：重启所有
python scripts/run_multi_trader.py restart
```

### Q2: 如何临时禁用某个实例？

**方式1：修改配置**
```yaml
- name: "trader_2"
  enabled: false  # 设置为false
```

**方式2：停止单个实例**
```bash
python scripts/run_multi_trader.py stop --instance trader_2
```

### Q3: 实例启动失败怎么办？

**检查步骤：**

1. 查看日志：
```bash
tail -50 logs/trader_1.log
```

2. 常见错误：
   - **私钥错误**: 检查`private_key`配置
   - **地址错误**: 检查`account_address`和`target_address`
   - **网络问题**: 检查网络连接
   - **余额不足**: 检查钱包余额

3. 测试配置：
```bash
# 使用调试模式启动
python scripts/run_multi_trader.py start --instance trader_1
# 观察输出信息
```

### Q4: 如何查看某个实例的交易情况？

```bash
# 查看最近的交易
grep "Trade\|Position\|Order" logs/trader_1.log | tail -20

# 查看今天的所有交易
grep "$(date +%Y-%m-%d)" logs/trader_1.log | grep "Trade"

# 统计交易次数
grep -c "Trade submitted" logs/trader_1.log
```

### Q5: 如何更改实例的跟单比例？

**步骤：**

1. 停止实例：
```bash
python scripts/run_multi_trader.py stop --instance trader_1
```

2. 修改配置：
```yaml
copy_trading:
  copy_ratio: 0.2  # 从0.1改为0.2
```

3. 重启实例：
```bash
python scripts/run_multi_trader.py start --instance trader_1
```

### Q6: 多个钱包可以跟踪同一个Leader吗？

**可以！** 这是常见场景：

```yaml
trading_instances:
  # 钱包1 - 激进策略
  - name: "wallet1_aggressive"
    target_address: "0xSAME_LEADER"  # 相同Leader
    hyperliquid:
      account_address: "0xWallet1"
    copy_trading:
      copy_ratio: 0.2

  # 钱包2 - 保守策略  
  - name: "wallet2_conservative"
    target_address: "0xSAME_LEADER"  # 相同Leader
    hyperliquid:
      account_address: "0xWallet2"
    copy_trading:
      copy_ratio: 0.05
```

### Q7: 如何安全停止所有实例？

```bash
# 方式1：使用脚本
python scripts/run_multi_trader.py stop

# 方式2：如果卡住，强制停止
pkill -f run_multi_trader

# 方式3：逐个停止
python scripts/run_multi_trader.py stop --instance trader_1
python scripts/run_multi_trader.py stop --instance trader_2
```

---

## 生产环境部署建议

### 1. 使用systemd服务（推荐）

创建服务文件：

```bash
sudo nano /etc/systemd/system/multi-trader.service
```

内容：
```ini
[Unit]
Description=Multi-Instance Copy Trader
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/your_user/perp-tools/copybot
ExecStart=/home/your_user/perp-tools/copybot/.venv/bin/python scripts/run_multi_trader.py monitor --config config/my_multi.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable multi-trader
sudo systemctl start multi-trader
sudo systemctl status multi-trader
```

### 2. 日志轮换

配置日志自动清理（已内置）：
- 自动按天轮换
- 保留7天日志
- 每日3:00自动清理

### 3. 监控告警

配置Telegram通知：
```yaml
global_settings:
  telegram:
    enabled: true
    bot_token: "your_token"
    chat_id: "your_chat_id"
```

### 4. 定期检查

```bash
# 添加到crontab
crontab -e

# 每小时检查一次状态
0 * * * * cd /home/your_user/perp-tools/copybot && /home/your_user/perp-tools/copybot/.venv/bin/python scripts/run_multi_trader.py status >> logs/health_check.log 2>&1
```

---

## 性能优化建议

### 1. 实例数量

- ✅ **推荐**: 3-5个实例
- ⚠️ **注意**: 超过10个实例可能影响性能
- 💡 **原因**: 每个实例都会查询API，过多会触发rate limit

### 2. 资源使用

单个实例大约占用：
- CPU: ~5-10%
- 内存: ~100-200MB
- 网络: ~1-5KB/s

### 3. API限制

Hyperliquid API限制：
- 建议实例间隔: 1-2秒启动
- 监控轮询间隔: 30秒
- WebSocket优先（减少REST调用）

---

## 安全建议

### 1. 私钥管理

⚠️ **永远不要：**
- 将私钥提交到Git
- 在公共地方分享配置文件
- 使用主钱包私钥

✅ **推荐做法：**
- 使用专门的交易钱包
- 限制每个钱包的资金量
- 定期更换钱包

### 2. 权限控制

```bash
# 限制配置文件权限
chmod 600 config/my_multi.yaml

# 限制日志目录权限
chmod 700 logs/
```

### 3. 备份配置

```bash
# 定期备份配置
cp config/my_multi.yaml config/backup/my_multi_$(date +%Y%m%d).yaml
```

---

## 故障排查清单

### 实例无法启动

- [ ] 检查配置文件语法（YAML格式）
- [ ] 验证私钥和地址格式
- [ ] 确认网络连接
- [ ] 查看日志错误信息
- [ ] 检查端口是否占用
- [ ] 验证Python环境

### 实例频繁崩溃

- [ ] 查看崩溃前的日志
- [ ] 检查内存使用情况
- [ ] 验证API调用频率
- [ ] 检查钱包余额
- [ ] 更新到最新版本

### 交易未执行

- [ ] 确认实例正在运行
- [ ] 检查Leader是否有交易
- [ ] 验证跟单比例设置
- [ ] 查看日志中的skip原因
- [ ] 确认钱包有足够余额
- [ ] 检查风控参数限制

### 日志过大

- [ ] 降低日志级别（INFO → WARNING）
- [ ] 检查日志轮换配置
- [ ] 手动清理旧日志
- [ ] 增加磁盘空间

---

## 总结

**多钱包多Leader跟单的核心优势：**

1. **风险分散** - 不同钱包独立运行，降低单点风险
2. **策略多样** - 同时运行多种跟单策略
3. **灵活管理** - 独立控制每个实例
4. **高可用** - 一个崩溃不影响其他
5. **易于扩展** - 随时添加新的跟单组合

**适用场景：**
- 跟踪多个不同的Leader
- 同一Leader不同策略测试
- 资金分散管理
- 多账户套利
- 风险对冲策略

**开始使用：**
1. 复制配置模板
2. 填写Leader地址和钱包信息
3. 启动实例
4. 查看日志确认运行

有问题随时查看日志或联系支持！
