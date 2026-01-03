# Per-Instance Risk Management（分钱包独立风控）

## 📋 功能说明

从此版本开始，多钱包模式支持为每个钱包配置独立的风险管理参数，包括：
- 止损比例 (stop_loss_ratio)
- 回撤限制 (max_drawdown)
- 止盈提醒 (take_profit_ratio，未实现)

**好处**：
- ✅ 不同钱包可以有不同的风险承受能力
- ✅ 大钱包可以更保守，小钱包可以更激进
- ✅ 止损触发时只影响单个钱包，不会全部停止

---

## 🔧 配置方法

### 1. 在 `config/my_multi.yaml` 中为每个instance添加 `risk_management` 配置

```yaml
trading_instances:
  - name: 'trader_wallet_1'
    enabled: true
    target_address: '0x...'

    hyperliquid:
      account_address: '0x...'
      private_key: '__FROM_ENV__'

    copy_trading:
      copy_ratio: 0.5
      # ... 其他参数

    # 钱包1：保守风控
    risk_management:
      max_drawdown: 0.08        # 8% 回撤警告
      stop_loss_ratio: 0.04     # 4% 止损自动平仓
      take_profit_ratio: 0.15   # 15% 止盈提醒（当前未实现）

  - name: 'trader_wallet_2'
    enabled: true
    target_address: '0x...'

    hyperliquid:
      account_address: '0x...'
      private_key: '__FROM_ENV__'

    copy_trading:
      copy_ratio: 0.35
      # ... 其他参数

    # 钱包2：激进风控
    risk_management:
      max_drawdown: 0.12        # 12% 回撤警告
      stop_loss_ratio: 0.06     # 6% 止损自动平仓
      take_profit_ratio: 0.2    # 20% 止盈提醒（当前未实现）
```

### 2. 如果不配置 `risk_management`

如果某个instance没有配置 `risk_management`，会使用全局 `.env` 中的配置：
```bash
MAX_DRAWDOWN=0.1            # 默认10%
STOP_LOSS_RATIO=0.05        # 默认5%
TAKE_PROFIT_RATIO=0.1       # 默认10%（未实现）
```

---

## ⚙️ 工作原理

### 环境变量注入
`run_multi_trader.py` 在启动每个instance之前，会将该instance的风控配置注入到环境变量中：

```python
# 为每个instance单独设置环境变量
risk_cfg = instance_config.get("risk_management", {}) or {}
if risk_cfg:
    if "max_drawdown" in risk_cfg:
        os.environ["MAX_DRAWDOWN"] = str(risk_cfg.get("max_drawdown"))
    if "stop_loss_ratio" in risk_cfg:
        os.environ["STOP_LOSS_RATIO"] = str(risk_cfg.get("stop_loss_ratio"))
```

### 读取优先级
`src/copy_trader.py` 读取风控参数的优先级：
1. 环境变量 (由 `run_multi_trader.py` 注入)
2. config字典中的 `risk_management` 配置
3. 默认值

```python
config['risk_management']['max_drawdown'] = float(
    os.getenv('MAX_DRAWDOWN',  # 优先环境变量
    config['risk_management'].get('max_drawdown', 0.1))  # 然后配置，最后默认值
)
```

---

## 📊 当前远程服务器配置

### 钱包1: trader_legacy (0x87e0...1C98)
- **风控策略**: 保守
- **回撤警告**: 8%
- **止损触发**: 4%
- **复制比例**: 50%

### 钱包2: trader_wallet_2997 (0xf5df...2997)
- **风控策略**: 激进
- **回撤警告**: 12%
- **止损触发**: 6%
- **复制比例**: 35%

---

## ⚠️ 重要说明

### 1. 独立止损
每个钱包的止损**独立计算**：
- 钱包1亏损4% → 只有钱包1触发止损并停止跟单
- 钱包2继续正常运行

### 2. 止损后的行为
当某个钱包触发止损时（根据 `.env` 全局配置）：
```bash
RISK_AUTO_CLOSE_ON_STOP_LOSS=true      # 自动平仓
RISK_HALT_TRADING_ON_STOP_LOSS=true    # 停止接收新跟单
RISK_AUTO_CLOSE_AND_STOP=false         # 不退出进程
RISK_AUTO_CLOSE_COOLDOWN_S=300         # 5分钟冷却期
```

### 3. take_profit_ratio 未实现
`take_profit_ratio` 参数目前**只是配置项**，代码中没有自动止盈逻辑。
- ✅ 好处: 不会限制你的盈利
- 📝 可留作未来扩展

---

## 🔍 验证配置

### 查看日志确认风控参数
```bash
# 查看钱包1的风控日志
ssh ... "cd ~/copybot_release && grep -i 'stop.*loss\|drawdown' logs/trader_legacy.log | head -20"

# 查看钱包2的风控日志
ssh ... "cd ~/copybot_release && grep -i 'stop.*loss\|drawdown' logs/trader_wallet_2997.log | head -20"
```

### 查看配置文件
```bash
ssh ... "cat ~/copybot_release/config/my_multi.yaml"
```

---

## 🎯 建议配置

### 保守策略（适合大资金）
```yaml
risk_management:
  max_drawdown: 0.05        # 5% 回撤警告
  stop_loss_ratio: 0.03     # 3% 止损
```

### 平衡策略（中等资金）
```yaml
risk_management:
  max_drawdown: 0.1         # 10% 回撤警告
  stop_loss_ratio: 0.05     # 5% 止损
```

### 激进策略（小资金/测试）
```yaml
risk_management:
  max_drawdown: 0.15        # 15% 回撤警告
  stop_loss_ratio: 0.08     # 8% 止损
```

---

## 📝 更新日志

**2026-01-02**: 实现per-instance风控功能
- ✅ 修改 `run_multi_trader.py` 支持独立风控配置
- ✅ 更新 `my_multi.yaml` 示例配置
- ✅ 部署到远程服务器并验证

---

## 🔗 相关文件

- 实现代码: [scripts/run_multi_trader.py#L186-L194](../scripts/run_multi_trader.py)
- 配置示例: [config/my_multi.yaml](../config/my_multi.yaml)
- 风控逻辑: [src/copy_trader.py#L1580-L1666](../src/copy_trader.py)
