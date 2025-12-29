#!/bin/bash
# 设置自动清理日志的cron任务

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "设置每日自动清理旧日志..."
echo "项目路径: $PROJECT_ROOT"

# 创建cron任务（每天凌晨3点运行）
CRON_CMD="0 3 * * * cd $PROJECT_ROOT && $PROJECT_ROOT/.venv/bin/python $PROJECT_ROOT/scripts/clean_old_logs.py --days 7 >> $PROJECT_ROOT/logs/cleanup.log 2>&1"

# 检查cron任务是否已存在
if crontab -l 2>/dev/null | grep -q "clean_old_logs.py"; then
    echo "✓ Cron任务已存在"
    echo "当前配置:"
    crontab -l | grep "clean_old_logs.py"
else
    # 添加新的cron任务
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "✓ Cron任务已添加"
    echo "配置: 每天凌晨3点清理超过7天的日志"
fi

echo ""
echo "查看所有cron任务:"
crontab -l

echo ""
echo "手动测试清理脚本（预览模式）:"
echo "cd $PROJECT_ROOT && .venv/bin/python scripts/clean_old_logs.py --dry-run"
