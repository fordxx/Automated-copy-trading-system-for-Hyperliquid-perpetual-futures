#!/usr/bin/env bash
#
# 一键部署更新脚本
#
# 功能:
# 1. 同步代码到服务器
# 2. 重启服务
# 3. 验证服务状态
# 4. 显示最新日志
#
# 使用方法:
#   ./scripts/deploy_update.sh                    # 部署到指定服务器（通过环境变量配置）
#   ./scripts/deploy_update.sh --dry-run          # 只显示将要执行的操作,不实际执行
#   ./scripts/deploy_update.sh --no-restart       # 只同步代码,不重启
#   ./scripts/deploy_update.sh --env-only         # 只同步.env文件

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置（允许用环境变量覆盖，避免硬编码本机路径/服务器信息）
# - COPYBOT_SERVER_IP: 服务器 IP
# - COPYBOT_SERVER_USER: 服务器用户（默认 ubuntu）
# - COPYBOT_SSH_KEY: SSH 私钥路径
# - COPYBOT_REMOTE_DIR: 远程部署目录
# - COPYBOT_MULTI_CONFIG: 多实例配置路径（默认 config/my_multi.yaml）
SERVER_IP="${COPYBOT_SERVER_IP:-}"
SERVER_USER="${COPYBOT_SERVER_USER:-ubuntu}"
SSH_KEY="${COPYBOT_SSH_KEY:-}"
REMOTE_DIR="${COPYBOT_REMOTE_DIR:-~/copybot_release}"
MULTI_CONFIG="${COPYBOT_MULTI_CONFIG:-config/my_multi.yaml}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 参数解析
DRY_RUN=false
NO_RESTART=false
ENV_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-restart)
            NO_RESTART=true
            shift
            ;;
        --env-only)
            ENV_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--dry-run] [--no-restart] [--env-only]"
            exit 1
            ;;
    esac
done

# 辅助函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

run_cmd() {
    local cmd="$1"
    local desc="${2:-}"

    if [ -n "$desc" ]; then
        log_info "$desc"
    fi

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would execute: $cmd"
        return 0
    else
        if eval "$cmd"; then
            return 0
        else
            log_error "Command failed: $cmd"
            return 1
        fi
    fi
}

ssh_cmd() {
    local cmd="$1"
    ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "$cmd"
}

# 主要功能函数

check_prerequisites() {
    log_info "Checking prerequisites..."

    if [[ -z "${SERVER_IP:-}" ]]; then
        log_error "Missing server IP: set COPYBOT_SERVER_IP"
        exit 1
    fi

    if [[ -z "${SSH_KEY:-}" ]]; then
        log_error "Missing SSH key path: set COPYBOT_SSH_KEY"
        exit 1
    fi

    # 检查SSH密钥
    if [ ! -f "$SSH_KEY" ]; then
        log_error "SSH key not found: $SSH_KEY"
        exit 1
    fi

    # 检查本地.env文件
    if [ ! -f "$LOCAL_DIR/.env" ]; then
        log_warning ".env file not found in local directory"
    fi

    # 测试SSH连接
    if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 "$SERVER_USER@$SERVER_IP" "echo 'SSH connection OK'" > /dev/null 2>&1; then
        log_error "Cannot connect to server $SERVER_IP"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

backup_remote_env() {
    log_info "Backing up remote .env file..."

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would backup remote .env"
        return 0
    fi

    ssh_cmd "cd $REMOTE_DIR && [ -f .env ] && cp .env .env.backup.\$(date +%Y%m%d_%H%M%S) || true"
    log_success "Remote .env backed up"
}

sync_code() {
    log_info "Syncing code to server..."

    local rsync_cmd="rsync -avz --delete \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='.git' \
        --exclude='logs/*.log' \
        --exclude='logs/*.pid' \
        --exclude='logs/*.lock' \
        --exclude='*.pyc' \
        --exclude='.claude' \
        -e \"ssh -i $SSH_KEY\" \
        \"$LOCAL_DIR/\" \
        \"$SERVER_USER@$SERVER_IP:$REMOTE_DIR/\""

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would execute: $rsync_cmd"
    else
        eval "$rsync_cmd"
        log_success "Code synced successfully"
    fi
}

sync_env_only() {
    log_info "Syncing .env file only..."

    if [ ! -f "$LOCAL_DIR/.env" ]; then
        log_error ".env file not found: $LOCAL_DIR/.env"
        exit 1
    fi

    backup_remote_env

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would sync .env file"
    else
        scp -i "$SSH_KEY" "$LOCAL_DIR/.env" "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/.env"
        log_success ".env file synced"
    fi
}

restart_service() {
    if $NO_RESTART; then
        log_info "Skipping service restart (--no-restart flag)"
        return 0
    fi

    log_info "Restarting copybot service..."

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would restart service"
        return 0
    fi

    # Prefer multi-trader restart when the config exists on remote.
    if ssh_cmd "cd $REMOTE_DIR && test -f \"$MULTI_CONFIG\" && test -x ./scripts/manage_multi_trader.sh"; then
        ssh_cmd "cd $REMOTE_DIR && ./scripts/manage_multi_trader.sh restart --config \"$MULTI_CONFIG\""
    else
        ssh_cmd "cd $REMOTE_DIR && ./scripts/manage_copy_trader.sh restart"
    fi
    log_success "Service restarted"

    # 等待服务启动
    sleep 2
}

check_service_status() {
    log_info "Checking service status..."

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would check service status"
        return 0
    fi

    if ssh_cmd "cd $REMOTE_DIR && test -f \"$MULTI_CONFIG\" && test -x ./scripts/manage_multi_trader.sh"; then
        ssh_cmd "cd $REMOTE_DIR && ./scripts/manage_multi_trader.sh status --config \"$MULTI_CONFIG\""
    else
        ssh_cmd "cd $REMOTE_DIR && ./scripts/manage_copy_trader.sh status"
    fi
}

show_recent_logs() {
    log_info "Showing recent logs..."

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would show logs"
        return 0
    fi

    echo ""
    echo "===== Last 20 lines of application log ====="
    ssh_cmd "cd $REMOTE_DIR && tail -20 logs/copy_trader.log"
    echo "============================================="
}

# 主流程
main() {
    echo "=========================================="
    echo "  Copy Trader Deployment Script"
    echo "=========================================="
    echo ""

    if $DRY_RUN; then
        log_warning "DRY-RUN MODE: No changes will be made"
        echo ""
    fi

    log_info "Target: $SERVER_USER@$SERVER_IP:$REMOTE_DIR"
    echo ""

    # 检查前置条件
    check_prerequisites
    echo ""

    if $ENV_ONLY; then
        # 只同步.env文件
        sync_env_only
        echo ""
        restart_service
        echo ""
        check_service_status
        echo ""
        show_recent_logs
    else
        # 完整部署
        sync_code
        echo ""
        restart_service
        echo ""
        check_service_status
        echo ""
        show_recent_logs
    fi

    echo ""
    log_success "Deployment completed!"
    echo ""

    if ! $DRY_RUN && ! $NO_RESTART; then
        log_info "Tip: Monitor logs with:"
        echo "  ssh -i $SSH_KEY $SERVER_USER@$SERVER_IP \"cd $REMOTE_DIR && ./scripts/manage_multi_trader.sh tail\""
    fi

    echo ""
}

# 运行主流程
main
