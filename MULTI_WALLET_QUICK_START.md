# 多钱包跟单快速参考

## 一分钟上手

```bash
# 1. 复制配置
cp config/multi_config.yaml config/my_multi.yaml

# 2. 编辑配置（填入你的地址和私钥）
nano config/my_multi.yaml

# 3. 启动
python scripts/run_multi_trader.py start --config config/my_multi.yaml

# 4. 查看状态
python scripts/run_multi_trader.py status
```

## 最小配置示例

```yaml
trading_instances:
  - name: "trader_1"
    enabled: true
    target_address: "0xLeaderAddress"
    hyperliquid:
      account_address: "0xYourWallet"
      private_key: "0xYourKey"
    copy_trading:
      copy_mode: "position"
      copy_ratio: 0.1
      max_position_size: 5.0
```

## 常用命令

```bash
# 启动所有
python scripts/run_multi_trader.py start

# 停止所有
python scripts/run_multi_trader.py stop

# 查看状态
python scripts/run_multi_trader.py status

# 启动单个
python scripts/run_multi_trader.py start --instance trader_1

# 查看日志
tail -f logs/trader_1.log

# 监控模式（推荐生产环境）
python scripts/run_multi_trader.py monitor
```

## 配置说明

| 参数 | 说明 | 示例 |
|-----|------|------|
| `name` | 实例名称（唯一） | "trader_1" |
| `enabled` | 是否启用 | true/false |
| `target_address` | Leader地址 | "0x123..." |
| `account_address` | 你的钱包地址 | "0xABC..." |
| `private_key` | 你的私钥 | "0xKEY..." |
| `copy_mode` | 跟单模式 | "position" 或 "wallet" |
| `copy_ratio` | 跟单比例 | 0.1 (10%) |
| `max_position_size` | 最大仓位 | 10.0 |
| `max_leverage` | 最大杠杆 | 5 |

## 两种跟单模式

### Position模式（推荐）
- 固定比例跟单
- 简单直接
- 例：Leader开100U，比例0.1，你开10U

### Wallet模式
- 动态钱包比例
- 自动调整
- 例：你1000U，Leader 10000U，自动0.1比例

## 典型场景

### 场景1：跟踪3个不同Leader
```yaml
trading_instances:
  - name: "follow_leader1"
    target_address: "0xLeader1"
    hyperliquid:
      account_address: "0xWallet1"
      private_key: "0xKey1"
    copy_trading:
      copy_ratio: 0.1
      
  - name: "follow_leader2"
    target_address: "0xLeader2"
    hyperliquid:
      account_address: "0xWallet2"
      private_key: "0xKey2"
    copy_trading:
      copy_ratio: 0.2
      
  - name: "follow_leader3"
    target_address: "0xLeader3"
    hyperliquid:
      account_address: "0xWallet3"
      private_key: "0xKey3"
    copy_trading:
      copy_ratio: 0.05
```

### 场景2：同Leader不同策略
```yaml
trading_instances:
  - name: "aggressive"
    target_address: "0xSameLeader"  # 相同
    hyperliquid:
      account_address: "0xWallet1"
    copy_trading:
      copy_ratio: 0.2  # 激进
      max_leverage: 10
      
  - name: "conservative"
    target_address: "0xSameLeader"  # 相同
    hyperliquid:
      account_address: "0xWallet2"
    copy_trading:
      copy_ratio: 0.05  # 保守
      max_leverage: 3
```

## 故障排查

### 实例无法启动
```bash
# 查看日志
tail -50 logs/trader_1.log

# 检查配置语法
python -c "import yaml; yaml.safe_load(open('config/my_multi.yaml'))"

# 测试单个实例
python scripts/run_multi_trader.py start --instance trader_1
```

### 交易未执行
- 检查Leader是否有交易
- 查看日志中的skip原因
- 确认钱包余额充足
- 验证跟单比例设置

### 查看交易记录
```bash
# 最近交易
grep "Trade" logs/trader_1.log | tail -20

# 今天的交易
grep "$(date +%Y-%m-%d)" logs/trader_1.log | grep "Trade"

# 统计交易数
grep -c "Trade submitted" logs/trader_1.log
```

## 安全建议

- ⚠️ 使用专门的交易钱包，不要用主钱包
- ⚠️ 限制每个钱包的资金量
- ⚠️ 不要将私钥提交到Git
- ⚠️ 定期检查日志和交易记录
- ✅ 配置文件权限设为600
- ✅ 使用监控模式自动重启
- ✅ 配置Telegram通知

## 生产环境部署

```bash
# 1. 使用监控模式后台运行
nohup python scripts/run_multi_trader.py monitor --config config/my_multi.yaml > monitor.log 2>&1 &

# 2. 或使用systemd服务
sudo systemctl enable multi-trader
sudo systemctl start multi-trader

# 3. 设置定时检查
crontab -e
# 添加：0 * * * * cd /path/to/copybot && python scripts/run_multi_trader.py status
```

## 完整文档

详细说明请查看：[MULTI_INSTANCE_GUIDE.md](MULTI_INSTANCE_GUIDE.md)
