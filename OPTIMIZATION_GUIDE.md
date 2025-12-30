# 项目优化指南

本文档介绍了最新添加的优化功能和工具。

## 优化总览

### 已实现的优化

1. ✅ **实时监控面板** - 可视化系统状态
2. ✅ **智能日志过滤** - 减少重复日志噪音
3. ✅ **交易统计报表** - 日报/周报/月报
4. ✅ **健康检查告警** - 自动检测异常
5. ✅ **一键部署更新** - 简化运维流程

---

## 1. 实时监控面板

### 功能
- 实时显示Leader和Follower账户状态
- 仓位比例准确度分析
- 进程运行状态监控
- 资源使用统计

### 使用方法

**完整模式** (自动刷新屏幕):
```bash
python scripts/monitor_dashboard.py
```

**紧凑模式** (适合终端日志):
```bash
python scripts/monitor_dashboard.py --compact
```

**自定义刷新间隔**:
```bash
python scripts/monitor_dashboard.py --interval 10  # 每10秒刷新
```

### 示例输出

```
====================================================================================================
                        🤖 HYPERLIQUID COPY TRADER MONITORING DASHBOARD
                                    2025-12-27 22:00:00
====================================================================================================

📡 PROCESS STATUS
----------------------------------------------------------------------------------------------------
Status      : ✅ RUNNING
PID         : 234581
Uptime      : 10:05:23
Memory      : 156.3 MB
CPU         : 0.5%

📊 LEADER ACCOUNT
----------------------------------------------------------------------------------------------------
Address     : 0xLeaderAddressExample123456789ABCDEF
Positions   : 15
Unrealized  : $1,234.56
Notional    : $25,678.90

👤 FOLLOWER ACCOUNT
----------------------------------------------------------------------------------------------------
Address     : 0xYourFollowerWalletExample123456789
Positions   : 12
Unrealized  : $234.56
Notional    : $5,135.78
Account Val : $83,386.32
Copy Ratio  : 50.0%

⚖️  RATIO ACCURACY (Top Deviations)
----------------------------------------------------------------------------------------------------
Coin       Leader Size    Follower Size     Actual%   Expected%       Dev%
----------------------------------------------------------------------------------------------------
⚠️ ANIME     -1156871       -500000       43.23       50.0        6.8
✅ BOME      -344234        -172117       50.01       50.0        0.0
```

### 服务器上使用

```bash
# SSH到服务器并运行监控
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169
cd ~/copybot_release
.venv/bin/python scripts/monitor_dashboard.py --compact --interval 10
```

---

## 2. 交易统计报表

### 功能
- 交易活动统计(成功/失败/跳过)
- 成交分析(数量/金额/手续费)
- 各币种详细统计
- 当前仓位快照
- 性能指标分析

### 使用方法

**今日报表**:
```bash
python scripts/trading_report.py --period today
```

**周报** (最近7天):
```bash
python scripts/trading_report.py --period week
```

**月报** (最近30天):
```bash
python scripts/trading_report.py --period month
```

**自定义时间范围**:
```bash
python scripts/trading_report.py --custom 2025-12-20 2025-12-27
```

### 示例输出

```
====================================================================================================
                                Weekly Trading Report (Last 7 Days)
                                 Generated at: 2025-12-27 22:25:18
====================================================================================================

📊 TRADING ACTIVITY
----------------------------------------------------------------------------------------------------
Total Trades     : 285
  ✅ Successful  : 250
  ❌ Failed      : 15
  ⏭️  Skipped    : 20
Coins Traded     : 25
Warnings         : 45
Errors           : 5

💰 FILL ANALYSIS
----------------------------------------------------------------------------------------------------
Total Fills      : 385
Total Volume     : $76,608.04
Total Fees       : $34.73

📈 BY COIN (Top 10 by Volume)
----------------------------------------------------------------------------------------------------
Coin            Fills             Volume            Fees         Closed PnL
----------------------------------------------------------------------------------------------------
ANIME              85 $        32,295.96 $         13.95 🟢 $          65.34
TST                16 $         4,391.07 $          3.53 🟢 $          73.20
...

💼 CURRENT POSITIONS
----------------------------------------------------------------------------------------------------
Open Positions   : 15
Total Notional   : $6,062.69
Unrealized PnL   : $734.82
Account Value    : $83,383.58

📉 PERFORMANCE METRICS
----------------------------------------------------------------------------------------------------
Avg Volume/Fill  : $198.98
Avg Fee/Fill     : $0.09
Fee Rate         : 0.0453%
Success Rate     : 87.72%
```

### 定时报表 (可选)

添加到crontab实现定时报表:

```bash
# 每天早上8点生成日报并通过邮件发送
0 8 * * * cd /home/ubuntu/copybot_release && .venv/bin/python scripts/trading_report.py --period today > /tmp/daily_report.txt 2>&1
```

---

## 3. 健康检查和告警

### 功能
- 进程运行状态检查
- 日志活动监控
- WebSocket连接检查
- 错误率分析
- 账户余额监控
- 仓位健康度检查
- 磁盘空间监控
- Telegram告警通知

### 使用方法

**单次检查**:
```bash
python scripts/health_check.py
```

**启用Telegram告警**:
```bash
python scripts/health_check.py --alert
```

**持续监控模式** (每10分钟检查一次):
```bash
python scripts/health_check.py --alert --continuous --interval 10
```

### 示例输出

```
================================================================================
                             🏥 HEALTH CHECK REPORT
                              2025-12-27 22:25:03
================================================================================
✅ Process Running           : Process running (PID: 234581)
✅ Log Activity              : Recent activity (2.3 minutes ago)
✅ WebSocket Connection      : WebSocket connected
✅ Recent Errors             : Error rate OK: 2 errors, 5 warnings
✅ Account Balance           : Balance OK: $83386.32
✅ Position Health           : PnL: $737.56 (12.17%)
✅ Disk Space                : Disk space OK: 935.68GB free
================================================================================
✅ All checks passed - System is healthy
================================================================================
```

### 作为系统服务运行 (推荐)

创建systemd服务用于持续健康监控:

```bash
# 在服务器上创建服务文件
sudo nano /etc/systemd/system/copybot-health.service
```

内容:
```ini
[Unit]
Description=Copybot Health Monitor
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/copybot_release
ExecStart=/home/ubuntu/copybot_release/.venv/bin/python /home/ubuntu/copybot_release/scripts/health_check.py --alert --continuous --interval 10
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

启用服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable copybot-health.service
sudo systemctl start copybot-health.service
```

---

## 4. 智能日志过滤器

### 功能
- 自动抑制重复日志消息
- 只在值变化时输出状态日志
- 累计被抑制的消息数量
- 重要消息(ERROR/WARNING)总是输出

### 使用方法

在主程序中启用智能日志过滤:

```python
from src.utils.smart_logger import setup_smart_logging

# 在logger配置后添加
logger = logging.getLogger(__name__)
setup_smart_logging(logger, throttle_seconds=60)
```

### 效果对比

**优化前**:
```
2025-12-27 12:00:00 - INFO - Status: 1 positions, Total PnL: $562.16
2025-12-27 12:00:30 - INFO - Status: 1 positions, Total PnL: $562.16
2025-12-27 12:01:00 - INFO - Status: 1 positions, Total PnL: $562.16
2025-12-27 12:01:30 - INFO - Status: 1 positions, Total PnL: $562.16
```

**优化后**:
```
2025-12-27 12:00:00 - INFO - Status: 1 positions, Total PnL: $562.16
2025-12-27 12:05:00 - INFO - Status: 1 positions, Total PnL: $563.20 (suppressed 9 similar messages in last 300s)
```

---

## 5. 一键部署更新脚本

### 功能
- 自动同步代码到服务器
- 自动重启服务
- 验证部署状态
- 显示最新日志
- 支持dry-run模式

### 使用方法

**完整部署**:
```bash
./scripts/deploy_update.sh
```

**只查看将执行的操作 (不实际执行)**:
```bash
./scripts/deploy_update.sh --dry-run
```

**只同步代码,不重启**:
```bash
./scripts/deploy_update.sh --no-restart
```

**只更新环境变量**:
```bash
./scripts/deploy_update.sh --env-only
```

### 部署流程

脚本会自动执行以下步骤:

1. ✅ 检查前置条件(SSH密钥、连接等)
2. ✅ 备份服务器上的.env文件
3. ✅ 同步代码到服务器(排除venv、日志等)
4. ✅ 重启copybot服务
5. ✅ 验证服务状态
6. ✅ 显示最新日志

### 示例输出

```
==========================================
  Copy Trader Deployment Script
==========================================

[INFO] Target: ubuntu@3.38.98.169:~/copybot_release

[INFO] Checking prerequisites...
[SUCCESS] Prerequisites check passed

[INFO] Syncing code to server...
sending incremental file list
./
src/copy_trader.py
scripts/health_check.py
[SUCCESS] Code synced successfully

[INFO] Restarting copybot service...
[SUCCESS] Service restarted

[INFO] Checking service status...
✅ Running | PID: 234581 | Uptime: 00:05

[SUCCESS] Deployment completed!

[INFO] Tip: Monitor logs with:
  ssh -i ... ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh tail app"
```

---

## 快速运维指南

### 日常监控

```bash
# 1. 查看实时状态
python scripts/monitor_dashboard.py --compact --interval 5

# 2. 每天查看报表
python scripts/trading_report.py --period today

# 3. 健康检查
python scripts/health_check.py
```

### 远程服务器监控

```bash
# SSH到服务器
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169

# 查看状态
cd ~/copybot_release && ./scripts/manage_copy_trader.sh status

# 运行监控面板
.venv/bin/python scripts/monitor_dashboard.py --compact

# 生成报表
.venv/bin/python scripts/trading_report.py --period week

# 健康检查
.venv/bin/python scripts/health_check.py
```

### 代码更新部署

```bash
# 在本地修改代码后
cd /home/fordxx/perp-tools/copybot

# 先dry-run查看将执行的操作
./scripts/deploy_update.sh --dry-run

# 确认无误后执行部署
./scripts/deploy_update.sh
```

---

## 性能优化建议

### 1. 日志管理

如果日志文件过大,定期清理:

```bash
# 压缩归档旧日志
cd ~/copybot_release/logs
gzip copy_trader.log.2025-12-20

# 或者使用logrotate自动管理
```

### 2. 监控优化

- 监控面板刷新间隔建议: 5-10秒
- 健康检查间隔建议: 10-30分钟
- 报表生成频率建议: 每天1次

### 3. 告警设置

只对critical问题发送Telegram告警:
- 进程停止
- WebSocket断开超过5分钟
- 错误率超过10%
- 账户余额低于阈值
- 持仓亏损超过20%

---

## 故障排查

### 监控面板无法连接API

```bash
# 检查网络连接
ping api.hyperliquid.xyz

# 检查环境变量
cat .env | grep HYPERLIQUID
```

### 报表数据为空

```bash
# 检查日志文件是否存在
ls -lh logs/copy_trader.log

# 检查时间范围是否正确
python scripts/trading_report.py --custom 2025-12-01 2025-12-31
```

### 健康检查误报

调整检查阈值:
- 修改 `scripts/health_check.py` 中的阈值参数
- 例如: `check_log_activity(minutes=30)` 调整为更长时间

---

## 下一步优化建议

### 短期(已完成 ✅)
- ✅ 实时监控面板
- ✅ 交易统计报表
- ✅ 健康检查告警
- ✅ 一键部署脚本

### 中期(待实现)
- 📊 Web Dashboard (基于Flask/FastAPI)
- 📈 历史数据可视化图表
- 🔔 更多告警渠道(邮件、Discord等)
- 📱 移动端监控APP

### 长期(待实现)
- 🤖 AI辅助交易策略优化
- 📉 风险评估和建议
- 🎯 多账户管理
- 🌐 集群部署支持

---

## 总结

通过这些优化,项目获得了:

1. **可观察性提升** - 实时监控和详细报表
2. **稳定性提升** - 健康检查和自动告警
3. **运维效率提升** - 一键部署和智能日志
4. **数据洞察** - 交易统计和性能分析

所有工具都已经过测试并可以立即使用。建议根据实际需求配置定时任务和告警阈值。

---

**最后更新**: 2025-12-27
**版本**: v1.1.0 (优化版)
