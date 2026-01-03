#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

PY="$ROOT_DIR/.venv/bin/python"
RUNNER="$ROOT_DIR/scripts/run_multi_trader.py"
DEFAULT_CONFIG="$ROOT_DIR/config/my_multi.yaml"
LOG_STDOUT="$ROOT_DIR/logs/multi_service_stdout.log"
PID_FILE="$ROOT_DIR/logs/multi_trader.pid"
LOCK_FILE="$ROOT_DIR/logs/multi_trader.lock"

mkdir -p "$ROOT_DIR/logs" || true

usage() {
  echo "Usage: $0 {start|stop|restart|status|tail} [--config path]"
}

get_config_path() {
  local cfg="$DEFAULT_CONFIG"
  if [[ "${1:-}" == "--config" && -n "${2:-}" ]]; then
    cfg="$2"
  fi
  echo "$cfg"
}

is_running() {
  [[ -n "$(monitor_pids)" ]]
}

monitor_pids() {
  # Prefer the actual python "monitor" process (not the flock wrapper).
  pgrep -af -- "$RUNNER" | grep -F " monitor" | awk -v py="$PY" '$2 == py {print $1}' || true
}

wrapper_pids() {
  # When we start with `flock`, the wrapper holds the lock for the lifetime of the monitor.
  pgrep -af -- "$RUNNER" | grep -F " monitor" | awk '$2 == "flock" {print $1}' || true
}

cleanup_orphan_procs() {
  # Clean leftover multiprocessing helpers from previous crashes (only for this repo venv).
  local stale
  stale="$(pgrep -af -- "$ROOT_DIR/.venv/bin/python -c from multiprocessing" | awk '{print $1}' || true)"
  if [[ -n "$stale" ]]; then
    echo "🧹 清理残留 multiprocessing 进程: $stale"
    for pid in $stale; do
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
}

status() {
  echo "--------------------------------------------------"
  echo "📌 Multi-trader 状态检查"
  echo "- 项目目录: $ROOT_DIR"
  echo "- PID 文件: $PID_FILE"
  echo "- 标准输出: $LOG_STDOUT"
  echo
  if ! is_running; then
    echo "🛑 未发现运行中的 multi-trader 监控进程"
    return 0
  fi
  local monitor_pids
  monitor_pids="$(monitor_pids)"
  echo "✅ monitor PID: $monitor_pids"
  for pid in $monitor_pids; do
    ps -o pid,ppid,stat,etime,cmd -p "$pid" || true
  done

  local wrapper_pids
  wrapper_pids="$(wrapper_pids)"
  if [[ -n "$wrapper_pids" ]]; then
    echo
    echo "🔒 lock wrapper PID: $wrapper_pids"
    for pid in $wrapper_pids; do
      ps -o pid,ppid,stat,etime,cmd -p "$pid" || true
    done
  fi
  echo
  echo "子实例日志文件（每个实例一个）:"
  ls -1 "$ROOT_DIR/logs"/*.log 2>/dev/null | xargs -n 1 basename | grep -v -E '^(multi_service_stdout|copy_trader)\\.log$' || true
  echo
  echo "子实例进程（monitor 的子进程）:"
  for pid in $monitor_pids; do
    ps -o pid,ppid,stat,etime,cmd --ppid "$pid" || true
  done
}

start_service() {
  local cfg
  cfg="$(get_config_path "${@:1}")"
  echo "--------------------------------------------------"
  echo "🚀 启动 multi-trader (monitor)"
  echo "- config: $cfg"

  if [[ ! -x "$PY" ]]; then
    echo "❌ 找不到虚拟环境 Python：$PY"
    return 1
  fi
  if [[ ! -f "$cfg" ]]; then
    echo "❌ 找不到配置文件：$cfg"
    return 1
  fi

  if is_running; then
    echo "⚠️ 已经在运行了（为了安全不会重复启动）。"
    status --config "$cfg"
    return 0
  fi

  cleanup_orphan_procs

  # 启动 monitor 进程，使用 Python 的单进程锁保护
  # 该锁将确保同时只有一个 monitor 进程运行
  echo "🔒 使用单进程锁启动..."
  nohup "$PY" "$RUNNER" monitor --config "$cfg" >> "$LOG_STDOUT" 2>&1 < /dev/null &
  
  sleep 1.5

  # Record PID by matching the monitor command (best-effort).
  local pid
  pid="$(monitor_pids | head -n 1 || true)"
  if [[ -n "$pid" ]]; then
    echo "$pid" > "$PID_FILE"
  fi

  if is_running; then
    echo "✅ 启动成功"
    status --config "$cfg"
    return 0
  fi

  echo "❌ 启动失败：未检测到 monitor 进程。请查看日志：$LOG_STDOUT"
  return 1
}

stop_service() {
  echo "--------------------------------------------------"
  echo "🛑 停止 multi-trader"
  if ! is_running; then
    echo "ℹ️ 没有在跑的 monitor 进程。"
    return 0
  fi

  local pids
  pids="$(monitor_pids)"
  echo "准备停止 monitor PID: $pids"
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done

  local wrappers
  wrappers="$(wrapper_pids)"
  if [[ -n "$wrappers" ]]; then
    echo "准备停止 lock wrapper PID: $wrappers"
    for pid in $wrappers; do
      kill -TERM "$pid" 2>/dev/null || true
    done
  fi

  sleep 1
  if is_running; then
    echo "⚠️ 仍在运行，强制停止..."
    pids="$(monitor_pids)"
    for pid in $pids; do
      kill -KILL "$pid" 2>/dev/null || true
    done
    wrappers="$(wrapper_pids)"
    for pid in $wrappers; do
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
  rm -f "$PID_FILE" || true
  echo "✅ 已停止"
}

tail_logs() {
  tail -n 100 -f "$LOG_STDOUT"
}

action="${1:-}"
shift || true

case "$action" in
  start) start_service "$@" ;;
  stop) stop_service ;;
  restart) stop_service && start_service "$@" ;;
  status) status "$@" ;;
  tail) tail_logs ;;
  *) usage; exit 2 ;;
esac
