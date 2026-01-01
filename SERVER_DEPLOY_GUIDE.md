# 服务器部署指南

## 服务器信息
- **服务器地址**: `<server_ip>`（示例）
- **SSH密钥**: 本机私钥路径（示例：`/path/to/key.pem`）
- **部署目录**: `~/copybot_release`（示例）

建议把这些信息放到环境变量里，避免在脚本/命令里反复硬编码：

```bash
export COPYBOT_SERVER_IP="<server_ip>"
export COPYBOT_SERVER_USER="ubuntu"
export COPYBOT_SSH_KEY="/path/to/key.pem"
export COPYBOT_REMOTE_DIR="~/copybot_release"
```
- **旧版封存**: `/home/ubuntu/archive/copybot_YYYY-MM-DD_HHMMSS`
- **用户**: ubuntu

## 连接服务器

```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP"
```

## 服务管理

### 多钱包模式（multi-trader）

推荐用 `monitor` 常驻进程运行多实例（自动拉起/重启崩溃实例）。

```bash
# 启动（后台 monitor）
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_multi_trader.sh start --config config/my_multi.yaml"

# 状态
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_multi_trader.sh status --config config/my_multi.yaml"

# 停止
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_multi_trader.sh stop"

# 查看 multi-trader stdout
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_multi_trader.sh tail"
```

### 查看状态
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh status"
```

### 启动服务
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh start"
```

### 停止服务
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh stop"
```

### 重启服务
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh restart"
```

## 日志查看

### 查看应用日志(最近50行)
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh last 50 app"
```

### 查看系统输出日志
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh last 50 stdout"
```

### 实时查看日志(需要按Ctrl+C退出)
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh tail app"
```

## 更新部署

当本地代码有更新时,同步到服务器:

```bash
# 1. 同步代码
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.git' --exclude='logs' --exclude='*.pyc' --exclude='.claude' -e "ssh -i $COPYBOT_SSH_KEY" /path/to/copybot/ "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP:$COPYBOT_REMOTE_DIR/"

# 2. 重启服务
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh restart"
```

## 更新环境变量

如果需要修改配置:

```bash
# 1. 编辑本地.env文件
nano /path/to/copybot/.env

# 2. 上传到服务器
scp -i "$COPYBOT_SSH_KEY" /path/to/copybot/.env "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP:$COPYBOT_REMOTE_DIR/.env"

# 3. 重启服务
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh restart"
```

### 多实例私钥（推荐：方案A）

多实例不要把私钥放进 `config/my_multi.yaml`，而是放到远程 `.env`，按实例名提供：

```bash
# 例：实例 name=trader_legacy
HYPERLIQUID_PRIVATE_KEY_TRADER_LEGACY=0x...

# 例：实例 name=trader_wallet_508f
HYPERLIQUID_PRIVATE_KEY_TRADER_WALLET_508F=0x...
```

并用校验脚本检查（在远程执行）：

```bash
cd $COPYBOT_REMOTE_DIR
./scripts/validate_env.sh --multi --config config/my_multi.yaml
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
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "sudo systemctl status copybot.service"

# 通过systemd启动
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "sudo systemctl start copybot.service"

# 通过systemd停止
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "sudo systemctl stop copybot.service"

# 禁用开机自启动
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "sudo systemctl disable copybot.service"

# 启用开机自启动
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "sudo systemctl enable copybot.service"
```

## 监控命令

### 查看进程
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "ps aux | grep python | grep copy_trader"
```

### 查看系统资源占用
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "top -bn1 | head -20"
```

### 查看磁盘使用
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "df -h"
```

### 查看内存使用
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "free -h"
```

## 故障排查

### 如果服务无法启动

1. 检查日志错误信息:
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && tail -100 logs/service_stdout.log"
```

2. 检查.env配置:
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/validate_env.sh"
```

3. 检查依赖是否完整:
```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && source .venv/bin/activate && pip list"
```

### 清理日志文件(当日志太大时)

```bash
ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh stop && > logs/copy_trader.log && > logs/service_stdout.log && ./scripts/manage_copy_trader.sh start"
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
alias copybot-ssh='ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP"'
alias copybot-status='ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh status"'
alias copybot-logs='ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh last 50 app"'
alias copybot-restart='ssh -i "$COPYBOT_SSH_KEY" "$COPYBOT_SERVER_USER@$COPYBOT_SERVER_IP" "cd $COPYBOT_REMOTE_DIR && ./scripts/manage_copy_trader.sh restart"'
```

然后执行 `source ~/.bashrc`,之后就可以用简化命令:
- `copybot-ssh` - 直接连接服务器
- `copybot-status` - 查看状态
- `copybot-logs` - 查看日志
- `copybot-restart` - 重启服务
