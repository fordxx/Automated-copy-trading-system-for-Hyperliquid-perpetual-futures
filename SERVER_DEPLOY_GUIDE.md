# 服务器部署指南

## 服务器信息
- **服务器地址**: 3.38.98.169
- **SSH密钥**: `/home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem`
- **部署目录**: `/home/ubuntu/copybot_release`
- **旧版封存**: `/home/ubuntu/archive/copybot_YYYY-MM-DD_HHMMSS`
- **用户**: ubuntu

## 连接服务器

```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169
```

## 服务管理

### 查看状态
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh status"
```

### 启动服务
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh start"
```

### 停止服务
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh stop"
```

### 重启服务
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh restart"
```

## 日志查看

### 查看应用日志(最近50行)
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh last 50 app"
```

### 查看系统输出日志
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh last 50 stdout"
```

### 实时查看日志(需要按Ctrl+C退出)
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh tail app"
```

## 更新部署

当本地代码有更新时,同步到服务器:

```bash
# 1. 同步代码
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.git' --exclude='logs' --exclude='*.pyc' --exclude='.claude' -e "ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem" /home/fordxx/perp-tools/copybot/ ubuntu@3.38.98.169:~/copybot_release/

# 2. 重启服务
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh restart"
```

## 更新环境变量

如果需要修改配置:

```bash
# 1. 编辑本地.env文件
nano /home/fordxx/perp-tools/copybot/.env

# 2. 上传到服务器
scp -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem /home/fordxx/perp-tools/copybot/.env ubuntu@3.38.98.169:~/copybot_release/.env

# 3. 重启服务
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh restart"
```

## 开机自启动

服务已配置systemd开机自启动:
- **服务名称**: copybot.service
- **服务文件**: /etc/systemd/system/copybot.service
- **状态**: enabled (开机自启动已启用)

服务器重启后会自动启动跟单机器人。

### 管理systemd服务(可选)

```bash
# 查看systemd服务状态
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "sudo systemctl status copybot.service"

# 通过systemd启动
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "sudo systemctl start copybot.service"

# 通过systemd停止
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "sudo systemctl stop copybot.service"

# 禁用开机自启动
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "sudo systemctl disable copybot.service"

# 启用开机自启动
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "sudo systemctl enable copybot.service"
```

## 监控命令

### 查看进程
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "ps aux | grep python | grep copy_trader"
```

### 查看系统资源占用
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "top -bn1 | head -20"
```

### 查看磁盘使用
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "df -h"
```

### 查看内存使用
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "free -h"
```

## 故障排查

### 如果服务无法启动

1. 检查日志错误信息:
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && tail -100 logs/service_stdout.log"
```

2. 检查.env配置:
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/validate_env.sh"
```

3. 检查依赖是否完整:
```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && source .venv/bin/activate && pip list"
```

### 清理日志文件(当日志太大时)

```bash
ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh stop && > logs/copy_trader.log && > logs/service_stdout.log && ./scripts/manage_copy_trader.sh start"
```

## 部署完成状态

✅ 服务器环境已配置
✅ Python 3.12 + 虚拟环境已安装
✅ 所有依赖包已安装
✅ 环境变量已配置(.env文件)
✅ 跟单服务已启动并正常运行
✅ WebSocket连接已建立,正在监控目标地址
✅ systemd服务已配置,开机自动启动已启用
✅ 日志系统正常工作

**当前状态**: 服务正常运行中,PID: 234581
**监控地址**: 0xLeaderAddressExample123456789ABCDEF
**当前仓位**: 1个持仓,总盈亏: $562.16

## 简化命令别名(可选)

为了简化命令,可以在本地添加bash别名。编辑 `~/.bashrc`:

```bash
# 添加到 ~/.bashrc
alias copybot-ssh='ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169'
alias copybot-status='ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh status"'
alias copybot-logs='ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh last 50 app"'
alias copybot-restart='ssh -i /home/fordxx/perp-tools/LightsailDefaultKey-ap-northeast-2.pem ubuntu@3.38.98.169 "cd ~/copybot_release && ./scripts/manage_copy_trader.sh restart"'
```

然后执行 `source ~/.bashrc`,之后就可以用简化命令:
- `copybot-ssh` - 直接连接服务器
- `copybot-status` - 查看状态
- `copybot-logs` - 查看日志
- `copybot-restart` - 重启服务
