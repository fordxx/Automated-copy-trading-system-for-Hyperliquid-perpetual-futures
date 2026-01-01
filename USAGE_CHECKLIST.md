# 系统使用前检查清单

## ✅ 系统就绪状态

### 核心功能检查（已完成）

- [x] 双模式跟单功能已实现
  - [x] Position模式（固定比例）
  - [x] Wallet模式（动态钱包比例）
  - [x] 失败安全机制（跳过交易，不降级）

- [x] 多钱包多Leader功能已实现
  - [x] 多实例管理器 (run_multi_trader.py)
  - [x] 交互式管理脚本 (manage_multi_trader.sh)
  - [x] 独立配置系统
  - [x] 进程隔离机制

- [x] 文档完整性
  - [x] 快速参考指南 (MULTI_WALLET_QUICK_START.md)
  - [x] 完整使用指南 (MULTI_INSTANCE_GUIDE.md)
  - [x] 模式对比文档 (COPY_MODE_GUIDE.md)
  - [x] 主要说明文档 (README.md)

---

## 🚀 开始使用前的准备

### 第一步：准备钱包和Leader地址

**你需要准备：**

1. **Leader地址** - 要跟单的目标地址
   - 从Hyperliquid浏览器获取
   - 确保是活跃交易的地址
   - 示例：`0x563C175E6f11582f65D6d9E360A618699DEe14a9`

2. **Follower钱包** - 你的跟单钱包
   - **账户地址**：你的钱包地址
   - **私钥**：⚠️ 使用专门的交易钱包，不要用主钱包
   - **余额**：确保有足够的USDC用于交易

3. **Telegram通知**（可选但推荐）
   - Bot Token：从 @BotFather 获取
   - Chat ID：从 @userinfobot 获取

### 第二步：选择使用方式

**方式1：单钱包跟单（简单）**
- 使用默认配置 `config/config.yaml`
- 适合：只跟踪一个Leader
- 参考：[QUICK_START.md](QUICK_START.md)

**方式2：多钱包跟单（推荐）**
- 使用多实例配置 `config/multi_config.yaml`
- 适合：跟踪多个Leader或多种策略
- 参考：[MULTI_WALLET_QUICK_START.md](MULTI_WALLET_QUICK_START.md)

---

## 📋 单钱包跟单（快速开始）

### 1. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置
nano .env
```

**必填项：**
```bash
TARGET_ADDRESS="0xLeaderAddress..."
HYPERLIQUID_ACCOUNT_ADDRESS="0xYourAddress..."
HYPERLIQUID_PRIVATE_KEY="0xYourPrivateKey..."
COPY_MODE="position"  # 或 "wallet"
COPY_RATIO="0.1"      # 10%
```

### 2. 启动

```bash
# 使用管理脚本
./scripts/manage_copy_trader.sh

# 或直接启动
python scripts/run_copy_trader.py
```

### 3. 验证

```bash
# 查看日志
tail -f logs/copy_trader.log

# 检查进程
./scripts/manage_copy_trader.sh status
```

---

## 🎯 多钱包跟单（完整功能）

### 1. 配置文件

```bash
# 复制配置模板
cp config/multi_config.yaml config/my_multi.yaml

# 编辑配置
nano config/my_multi.yaml
```

**最简配置：**
```yaml
trading_instances:
  - name: "trader_1"
    enabled: true
    target_address: "0xLeaderAddress1"
    
    hyperliquid:
      account_address: "0xYourWallet1"
      private_key: "__FROM_ENV__"
    
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.1
      max_position_size: 5.0
```

配套的 `.env`（按实例名提供私钥）：
```bash
HYPERLIQUID_PRIVATE_KEY_TRADER_1=0x...
```

### 2. 启动

```bash
# 方式1：交互式菜单
./scripts/manage_multi_trader.sh

# 方式2：命令行
python scripts/run_multi_trader.py start --config config/my_multi.yaml
```

### 3. 验证

```bash
# 查看状态
python scripts/run_multi_trader.py status --config config/my_multi.yaml

# 查看日志
tail -f logs/trader_1.log
```

**预期输出：**
```
================================================================================
                             MULTI-INSTANCE STATUS                              
================================================================================

✅ trader_1             RUNNING (PID: 12345)
   Leader: 0xLeader1...
   Follower: 0xYour1...
   Mode: position (ratio: 0.1)
   
================================================================================
Summary: 1 running, 0 stopped, 0 disabled
================================================================================
```

---

## ⚠️ 使用前注意事项

### 安全检查

- [ ] ✅ 已使用专门的交易钱包（不是主钱包）
- [ ] ✅ 已限制每个钱包的资金量
- [ ] ✅ 私钥文件权限设置为600
- [ ] ✅ 配置文件不包含在Git中
- [ ] ✅ 已配置Telegram通知

### 配置检查

- [ ] ✅ Leader地址格式正确（0x开头，42字符）
- [ ] ✅ 私钥格式正确（0x开头，66字符）
- [ ] ✅ 跟单比例合理（建议0.01-0.2）
- [ ] ✅ 最大仓位设置合理
- [ ] ✅ 钱包有足够余额

### 测试建议

**首次使用强烈建议：**

1. **使用测试网测试**
   ```bash
   HYPERLIQUID_ENV=testnet python scripts/run_copy_trader.py
   ```

2. **使用小额测试**
   ```yaml
   copy_trading:
     copy_ratio: 0.01  # 1%
     max_position_size: 0.5
   ```

3. **观察几笔交易**
   - 检查日志中的交易记录
   - 验证下单金额是否正确
   - 确认没有错误信息

---

## 🔍 验证系统是否正常

### 基础测试

```bash
# 1. 检查配置文件格式
python -c "import yaml; yaml.safe_load(open('config/multi_config.yaml'))"

# 2. 测试状态查询
python scripts/run_multi_trader.py status

# 3. 查看帮助信息
python scripts/run_multi_trader.py --help
```

### 功能测试

```bash
# 1. 启动单个实例测试
python scripts/run_multi_trader.py start --instance trader_1

# 2. 查看日志确认启动
tail -20 logs/trader_1.log

# 3. 检查进程
ps aux | grep run_copy_trader

# 4. 停止测试
python scripts/run_multi_trader.py stop --instance trader_1
```

---

## 📊 监控运行状态

### 实时监控

```bash
# 查看实时日志
tail -f logs/trader_1.log

# 查看状态
watch -n 5 'python scripts/run_multi_trader.py status'

# 查看系统资源
htop  # 或 top
```

### 日志分析

```bash
# 查看错误
grep -i error logs/trader_1.log

# 查看交易记录
grep "Trade" logs/trader_1.log | tail -20

# 查看今天的交易
grep "$(date +%Y-%m-%d)" logs/trader_1.log | grep "Trade"

# 统计交易数量
grep -c "Trade submitted" logs/trader_1.log
```

---

## 🆘 遇到问题？

### 常见问题排查

**1. 实例无法启动**
```bash
# 查看详细日志
tail -50 logs/trader_1.log

# 检查配置
python -c "import yaml; print(yaml.safe_load(open('config/my_multi.yaml')))"

# 检查Python环境
which python
python --version
```

**2. 交易未执行**
- 检查Leader是否有新交易
- 查看日志中的skip原因
- 确认钱包余额充足
- 验证跟单比例设置

**3. Wallet模式失败**
- 检查网络连接
- 验证Leader地址是否有余额
- 查看是否有API限制

### 获取帮助

- 📖 查看文档：[MULTI_INSTANCE_GUIDE.md](MULTI_INSTANCE_GUIDE.md)
- 🔍 查看FAQ：[COPY_MODE_GUIDE.md](COPY_MODE_GUIDE.md#常见问题-faq)
- 📝 检查日志：`tail -100 logs/trader_1.log`

---

## ✅ 确认可以使用

**如果以下都正常，系统就可以使用了：**

- [x] ✅ 配置文件格式正确
- [x] ✅ 核心模块导入成功
- [x] ✅ 状态查询命令正常
- [x] ✅ 帮助信息显示正常
- [x] ✅ 文档完整且清晰

**测试验证结果：**
```
✅ 配置文件格式正确
✅ 找到 3 个实例配置
✅ copy_trader模块导入成功
✅ position_manager模块导入成功
✅ copy_mode参数已添加
✅ leader_address参数已添加
✅ get_account_value_usd支持address参数
✅ 所有核心功能已实现
```

---

## 🎉 开始使用

**推荐流程：**

1. **准备阶段**（5分钟）
   - 准备Leader地址和钱包私钥
   - 复制配置文件
   - 填写配置

2. **测试阶段**（建议30分钟）
   - 使用小额或测试网测试
   - 观察几笔交易
   - 确认运行正常

3. **正式运行**
   - 调整到正式比例
   - 启动监控模式
   - 配置Telegram通知

**快速开始命令：**
```bash
# 单钱包
./scripts/manage_copy_trader.sh

# 多钱包
./scripts/manage_multi_trader.sh
```

祝交易顺利！🚀
