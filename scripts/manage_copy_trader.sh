#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

PY="$ROOT_DIR/.venv/bin/python"
RUNNER="$ROOT_DIR/scripts/run_copy_trader.py"
LOG_STDOUT="$ROOT_DIR/logs/service_stdout.log"
LOG_APP="$ROOT_DIR/logs/copy_trader.log"
PID_FILE="$ROOT_DIR/logs/copy_trader.pid"
LOCK_FILE="$ROOT_DIR/logs/copy_trader.lock"

mkdir -p "$ROOT_DIR/logs" || true

echo_line() {
  echo "--------------------------------------------------"
}

require_venv() {
  if [[ ! -x "$PY" ]]; then
    echo "❌ 找不到虚拟环境 Python：$PY"
    echo "请先运行：./scripts/setup.sh"
    return 1
  fi
  return 0
}

running_pids() {
  # Scope to this workspace's runner path to avoid killing other copies of the bot
  # that happen to live elsewhere on the same machine.
  pgrep -af -- "$RUNNER" | awk '{print $1}' || true
}

is_running() {
  [[ -n "$(running_pids)" ]]
}

status() {
  echo_line
  echo "📌 状态检查"
  echo "- 项目目录: $ROOT_DIR"
  echo "- PID 文件: $PID_FILE"
  echo "- 锁文件:   $LOCK_FILE"
  echo "- 日志:     $LOG_STDOUT"
  echo "- 日志:     $LOG_APP"
  echo

  local pids
  pids="$(running_pids)"
  if [[ -z "$pids" ]]; then
    echo "🛑 未发现运行中的进程"
    return 0
  fi

  echo "✅ 运行中 PID: $pids"
  for pid in $pids; do
    ps -o pid,ppid,stat,etime,cmd -p "$pid" || true
  done
}

start_service() {
  echo_line
  echo "🚀 启动服务"
  if ! require_venv; then
    return 1
  fi

  if is_running; then
    echo "⚠️ 已经在运行了（为了安全不会重复启动）。"
    status
    return 0
  fi

  # 关键：必须把服务进程彻底与当前终端/进程组分离。
  # 否则在本菜单里 tail -f 按 Ctrl+C（SIGINT）时，可能会把服务一起中断。
  # 优先用 setsid 创建新 session；否则退化到 nohup，并强制 stdin=/dev/null。
  if command -v setsid >/dev/null 2>&1; then
    setsid -f "$PY" "$RUNNER" >> "$LOG_STDOUT" 2>&1 < /dev/null
  else
    nohup "$PY" "$RUNNER" >> "$LOG_STDOUT" 2>&1 < /dev/null &
  fi

  # 等一会儿让程序写 PID 文件、输出日志
  sleep 0.8

  if is_running; then
    echo "✅ 启动成功"
    status
    return 0
  fi

  echo "❌ 启动失败：未检测到进程。请查看日志："
  echo "- $LOG_STDOUT"
  return 1
}

stop_service() {
  echo_line
  echo "🛑 停止服务"

  local pids
  pids="$(running_pids)"

  if [[ -z "$pids" ]]; then
    echo "ℹ️ 没有在跑的进程。"
    return 0
  fi

  echo "准备停止 PID: $pids"

  # 优先用 PID 文件优雅退出（SIGTERM）；若 PID 文件缺失则对所有匹配进程发 SIGTERM
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  else
    for pid in $pids; do
      kill -TERM "$pid" 2>/dev/null || true
    done
  fi

  # Wait a bit for graceful shutdown.
  local waited=0
  while is_running && [[ $waited -lt 6 ]]; do
    sleep 1
    waited=$((waited + 1))
  done

  # 如果还存在，强制杀掉（避免重复下单风险）
  if is_running; then
    echo "⚠️ 仍有残留进程，执行强制停止..."
    pkill -9 -f -- "$RUNNER" || true
    sleep 0.8
  fi

  if is_running; then
    echo "❌ 停止失败：还有进程存在。"
    status
    return 1
  fi

  echo "✅ 已停止"
  return 0
}

restart_service() {
  echo_line
  echo "🔄 重启服务"
  stop_service || true
  start_service
}

tail_logs() {
  echo_line
  echo "📜 实时查看日志（按 Ctrl+C 退出查看；不会停止服务）"
  echo "1) service_stdout.log（启动/STDOUT）"
  echo "2) copy_trader.log（应用日志）"
  read -rp "请选择 [1-2]：" choice
  case "$choice" in
    2)
      echo "tail -f $LOG_APP"
      tail -f "$LOG_APP"
      ;;
    *)
      echo "tail -f $LOG_STDOUT"
      tail -f "$LOG_STDOUT"
      ;;
  esac
}

show_last_logs() {
  echo_line
  echo "📄 查看最近日志"
  read -rp "显示多少行？(默认 200)：" n
  n=${n:-200}
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    n=200
  fi

  echo "1) service_stdout.log（启动/STDOUT）"
  echo "2) copy_trader.log（应用日志）"
  read -rp "请选择 [1-2]：" choice
  case "$choice" in
    2)
      echo_line
      tail -n "$n" "$LOG_APP" || true
      ;;
    *)
      echo_line
      tail -n "$n" "$LOG_STDOUT" || true
      ;;
  esac
}

menu() {
  while true; do
    echo
    echo "========== Hyperliquid 跟单机器人 管理菜单 =========="
    echo "1) 启动"
    echo "2) 停止"
    echo "3) 重启"
    echo "4) 查看状态/进程"
    echo "5) 实时看日志 (tail -f)"
    echo "6) 看最近日志 (tail -n)"
    echo "0) 退出"
    echo "====================================================="
    read -rp "请输入选项 [0-6]：" opt
    case "$opt" in
      1) start_service ;;
      2) stop_service ;;
      3) restart_service ;;
      4) status ;;
      5) tail_logs ;;
      6) show_last_logs ;;
      0) echo "Bye"; exit 0 ;;
      *) echo "请输入 0-6" ;;
    esac
  done
}

if [[ $# -gt 0 ]]; then
  cmd="$1"
  shift || true
  case "$cmd" in
    start) start_service ;;
    stop) stop_service ;;
    restart) restart_service ;;
    status) status ;;
    tail)
      # Non-interactive tail: default to app log; pass "stdout" to follow service stdout.
      which_log="${1:-app}"
      if [[ "$which_log" == "stdout" ]]; then
        tail -f "$LOG_STDOUT"
      else
        tail -f "$LOG_APP"
      fi
      ;;
    last)
      # Non-interactive last: show last N lines; default 200.
      n="${1:-200}"
      which_log="${2:-app}"
      if ! [[ "$n" =~ ^[0-9]+$ ]]; then
        n=200
      fi
      if [[ "$which_log" == "stdout" ]]; then
        tail -n "$n" "$LOG_STDOUT" || true
      else
        tail -n "$n" "$LOG_APP" || true
      fi
      ;;
    *)
      echo "Usage: $0 {start|stop|restart|status|tail [app|stdout]|last [N] [app|stdout]}"
      exit 2
      ;;
  esac
  exit $?
fi

menu
