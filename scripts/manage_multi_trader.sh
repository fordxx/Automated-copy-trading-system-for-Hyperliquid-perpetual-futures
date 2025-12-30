#!/bin/bash
# Multi-Instance Copy Trader Management Script
# 多实例跟单管理脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MULTI_SCRIPT="$PROJECT_ROOT/scripts/run_multi_trader.py"
CONFIG_FILE="$PROJECT_ROOT/config/multi_config.yaml"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查虚拟环境
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${RED}❌ Virtual environment not found${NC}"
    echo "Please run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 检查配置文件
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ Config file not found: $CONFIG_FILE${NC}"
    echo "Please create config/multi_config.yaml"
    exit 1
fi

# 显示菜单
show_menu() {
    echo ""
    echo "=========================================="
    echo "  🤖 Multi-Instance Copy Trader Manager"
    echo "=========================================="
    echo ""
    echo "1) Start All Instances    - 启动所有实例"
    echo "2) Stop All Instances     - 停止所有实例"
    echo "3) Restart All Instances  - 重启所有实例"
    echo "4) Status                 - 查看状态"
    echo "5) Monitor Mode           - 监控模式（自动重启）"
    echo ""
    echo "6) Start Single Instance  - 启动单个实例"
    echo "7) Stop Single Instance   - 停止单个实例"
    echo ""
    echo "8) View Logs              - 查看日志"
    echo "9) Edit Config            - 编辑配置"
    echo ""
    echo "0) Exit                   - 退出"
    echo ""
    echo "=========================================="
}

# 启动所有实例
start_all() {
    echo -e "${GREEN}🚀 Starting all instances...${NC}"
    "$VENV_PYTHON" "$MULTI_SCRIPT" start
}

# 停止所有实例
stop_all() {
    echo -e "${YELLOW}🛑 Stopping all instances...${NC}"
    "$VENV_PYTHON" "$MULTI_SCRIPT" stop
}

# 重启所有实例
restart_all() {
    echo -e "${BLUE}🔄 Restarting all instances...${NC}"
    "$VENV_PYTHON" "$MULTI_SCRIPT" restart
}

# 查看状态
show_status() {
    "$VENV_PYTHON" "$MULTI_SCRIPT" status
}

# 监控模式
monitor_mode() {
    echo -e "${BLUE}📊 Entering monitor mode (Press Ctrl+C to exit)...${NC}"
    echo ""
    "$VENV_PYTHON" "$MULTI_SCRIPT" monitor
}

# 启动单个实例
start_single() {
    echo ""
    echo "Available instances (from config):"
    echo ""
    # 从配置文件提取实例名称
    grep "name:" "$CONFIG_FILE" | sed 's/.*name: "\(.*\)"/  - \1/'
    echo ""
    read -p "Enter instance name to start: " instance_name
    
    if [ -z "$instance_name" ]; then
        echo -e "${RED}❌ Instance name cannot be empty${NC}"
        return
    fi
    
    echo -e "${GREEN}🚀 Starting instance: $instance_name${NC}"
    "$VENV_PYTHON" "$MULTI_SCRIPT" start --instance "$instance_name"
}

# 停止单个实例
stop_single() {
    echo ""
    show_status
    echo ""
    read -p "Enter instance name to stop: " instance_name
    
    if [ -z "$instance_name" ]; then
        echo -e "${RED}❌ Instance name cannot be empty${NC}"
        return
    fi
    
    echo -e "${YELLOW}🛑 Stopping instance: $instance_name${NC}"
    "$VENV_PYTHON" "$MULTI_SCRIPT" stop --instance "$instance_name"
}

# 查看日志
view_logs() {
    echo ""
    echo "Available log files:"
    echo ""
    
    LOG_DIR="$PROJECT_ROOT/logs"
    if [ -d "$LOG_DIR" ]; then
        ls -1 "$LOG_DIR"/*.log 2>/dev/null | while read -r log_file; do
            basename "$log_file"
        done
    else
        echo "No logs directory found"
        return
    fi
    
    echo ""
    read -p "Enter log file name (or 'all' for all logs): " log_name
    
    if [ -z "$log_name" ]; then
        echo -e "${RED}❌ Log file name cannot be empty${NC}"
        return
    fi
    
    if [ "$log_name" = "all" ]; then
        tail -f "$LOG_DIR"/*.log
    else
        if [ -f "$LOG_DIR/$log_name" ]; then
            tail -f "$LOG_DIR/$log_name"
        else
            echo -e "${RED}❌ Log file not found: $log_name${NC}"
        fi
    fi
}

# 编辑配置
edit_config() {
    if command -v nano &> /dev/null; then
        nano "$CONFIG_FILE"
    elif command -v vim &> /dev/null; then
        vim "$CONFIG_FILE"
    elif command -v vi &> /dev/null; then
        vi "$CONFIG_FILE"
    else
        echo -e "${RED}❌ No text editor found (nano/vim/vi)${NC}"
        echo "Config file location: $CONFIG_FILE"
    fi
}

# 主循环
main() {
    while true; do
        show_menu
        read -p "Select option [0-9]: " choice
        
        case $choice in
            1) start_all ;;
            2) stop_all ;;
            3) restart_all ;;
            4) show_status ;;
            5) monitor_mode ;;
            6) start_single ;;
            7) stop_single ;;
            8) view_logs ;;
            9) edit_config ;;
            0) 
                echo -e "${GREEN}👋 Goodbye!${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}❌ Invalid option${NC}"
                ;;
        esac
        
        echo ""
        read -p "Press Enter to continue..."
    done
}

# 如果提供了命令行参数，直接执行命令
if [ $# -gt 0 ]; then
    case $1 in
        start) start_all ;;
        stop) stop_all ;;
        restart) restart_all ;;
        status) show_status ;;
        monitor) monitor_mode ;;
        *) 
            echo "Usage: $0 {start|stop|restart|status|monitor}"
            exit 1
            ;;
    esac
else
    # 否则显示交互式菜单
    main
fi
