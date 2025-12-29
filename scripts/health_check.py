#!/usr/bin/env python3
"""
健康检查和告警工具

功能:
1. 检查服务是否运行
2. 检查WebSocket连接
3. 检查最近是否有交易活动
4. 检查错误率
5. 检查账户状态
6. 异常时发送Telegram告警

使用方法:
    python scripts/health_check.py
    python scripts/health_check.py --alert  # 异常时发送Telegram告警
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.utils import constants

load_dotenv()


class HealthChecker:
    """健康检查器"""

    def __init__(self, send_alert=False):
        self.send_alert = send_alert
        self.follower_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')

        base_url = constants.TESTNET_API_URL if os.getenv('HYPERLIQUID_ENV') == 'testnet' else constants.MAINNET_API_URL
        self.info = Info(base_url, skip_ws=True)

        self.checks: List[Tuple[str, bool, str]] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []

    def check_process_running(self) -> Tuple[bool, str]:
        """检查进程是否运行"""
        try:
            pid_file = Path(__file__).parent.parent / 'logs' / 'copy_trader.pid'

            if not pid_file.exists():
                return False, "PID file not found"

            with open(pid_file, 'r') as f:
                pid = f.read().strip()

            # 检查进程是否存在
            import subprocess
            result = subprocess.run(
                ['ps', '-p', pid],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                return True, f"Process running (PID: {pid})"
            else:
                return False, f"Process not found (PID: {pid})"

        except Exception as e:
            return False, f"Error checking process: {e}"

    def check_log_activity(self, minutes=10) -> Tuple[bool, str]:
        """检查日志最近是否有活动"""
        try:
            log_file = Path(__file__).parent.parent / 'logs' / 'copy_trader.log'

            if not log_file.exists():
                return False, "Log file not found"

            # 检查文件修改时间
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            now = datetime.now()
            time_diff = (now - mtime).total_seconds() / 60

            if time_diff > minutes:
                return False, f"No log activity in last {time_diff:.1f} minutes"
            else:
                return True, f"Recent activity ({time_diff:.1f} minutes ago)"

        except Exception as e:
            return False, f"Error checking log: {e}"

    def check_recent_errors(self, minutes=60) -> Tuple[bool, str]:
        """检查最近是否有过多错误"""
        try:
            log_file = Path(__file__).parent.parent / 'logs' / 'copy_trader.log'

            if not log_file.exists():
                return True, "No log file"

            # 读取最近的日志
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            error_count = 0
            warning_count = 0
            total_lines = 0

            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('2025-'):
                        try:
                            timestamp_str = line.split(' - ')[0]
                            log_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')

                            if log_time < cutoff_time:
                                continue

                            total_lines += 1

                            if 'ERROR' in line:
                                error_count += 1
                            elif 'WARNING' in line:
                                warning_count += 1

                        except (ValueError, IndexError):
                            continue

            # 评估错误率
            if total_lines == 0:
                return True, "No recent logs"

            error_rate = (error_count / total_lines) * 100

            if error_count > 50:
                return False, f"High error count: {error_count} errors in {minutes}min"
            elif error_rate > 10:
                return False, f"High error rate: {error_rate:.1f}% ({error_count}/{total_lines})"
            else:
                return True, f"Error rate OK: {error_count} errors, {warning_count} warnings"

        except Exception as e:
            return False, f"Error checking logs: {e}"

    def check_websocket_connection(self) -> Tuple[bool, str]:
        """检查WebSocket连接状态"""
        try:
            log_file = Path(__file__).parent.parent / 'logs' / 'copy_trader.log'

            if not log_file.exists():
                return False, "No log file"

            # 查找最近的WebSocket相关日志
            cutoff_time = datetime.now() - timedelta(minutes=5)
            ws_connected = False
            ws_error = False

            with open(log_file, 'r', encoding='utf-8') as f:
                for line in reversed(list(f)):
                    if line.startswith('2025-'):
                        try:
                            timestamp_str = line.split(' - ')[0]
                            log_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')

                            if log_time < cutoff_time:
                                break

                            if 'Websocket connected' in line or 'WebSocket subscription active' in line:
                                ws_connected = True
                                break
                            elif 'Websocket connection closed' in line or 'WebSocket error' in line:
                                ws_error = True
                                break

                        except (ValueError, IndexError):
                            continue

            if ws_connected:
                return True, "WebSocket connected"
            elif ws_error:
                return False, "WebSocket connection error detected"
            else:
                return True, "WebSocket status unknown (no recent logs)"

        except Exception as e:
            return False, f"Error checking WebSocket: {e}"

    def check_account_balance(self) -> Tuple[bool, str]:
        """检查账户余额"""
        try:
            user_state = self.info.user_state(self.follower_address)
            account_value = float(user_state.get('marginSummary', {}).get('accountValue', 0))

            # 检查账户价值
            min_balance = 10.0  # 最低余额警告阈值

            if account_value < min_balance:
                return False, f"Low balance: ${account_value:.2f}"
            else:
                return True, f"Balance OK: ${account_value:.2f}"

        except Exception as e:
            return False, f"Error checking balance: {e}"

    def check_position_health(self) -> Tuple[bool, str]:
        """检查仓位健康度"""
        try:
            user_state = self.info.user_state(self.follower_address)
            positions = user_state.get('assetPositions', [])

            if not positions:
                return True, "No open positions"

            # 计算总未实现盈亏
            total_pnl = sum(float(pos['position'].get('unrealizedPnl', 0)) for pos in positions)
            total_notional = sum(
                abs(float(pos['position'].get('szi', 0)) * float(pos['position'].get('entryPx', 0)))
                for pos in positions
            )

            # 检查是否有大额亏损
            if total_notional > 0:
                pnl_ratio = (total_pnl / total_notional) * 100

                if pnl_ratio < -20:  # 亏损超过20%
                    return False, f"Large unrealized loss: {pnl_ratio:.2f}% (${total_pnl:.2f})"
                else:
                    return True, f"PnL: ${total_pnl:.2f} ({pnl_ratio:.2f}%)"
            else:
                return True, "Positions exist but no notional"

        except Exception as e:
            return False, f"Error checking positions: {e}"

    def check_disk_space(self) -> Tuple[bool, str]:
        """检查磁盘空间"""
        try:
            import shutil
            log_dir = Path(__file__).parent.parent / 'logs'

            if log_dir.exists():
                total, used, free = shutil.disk_usage(log_dir)
                free_gb = free / (1024 ** 3)
                free_percent = (free / total) * 100

                if free_gb < 1:  # 小于1GB
                    return False, f"Low disk space: {free_gb:.2f}GB free ({free_percent:.1f}%)"
                elif free_gb < 5:  # 小于5GB警告
                    self.warnings.append(f"Disk space low: {free_gb:.2f}GB free")
                    return True, f"Disk space: {free_gb:.2f}GB free ({free_percent:.1f}%)"
                else:
                    return True, f"Disk space OK: {free_gb:.2f}GB free"
            else:
                return True, "Log directory not found"

        except Exception as e:
            return False, f"Error checking disk: {e}"

    def send_telegram_alert(self, message: str):
        """发送Telegram告警"""
        if not self.send_alert:
            return

        try:
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            chat_id = os.getenv('TELEGRAM_CHAT_ID')

            if not bot_token or not chat_id:
                print("⚠️  Telegram not configured, skipping alert")
                return

            import requests
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': f"🚨 *Health Check Alert*\n\n{message}",
                'parse_mode': 'Markdown'
            }

            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                print("✅ Alert sent via Telegram")
            else:
                print(f"❌ Failed to send Telegram alert: {response.status_code}")

        except Exception as e:
            print(f"❌ Error sending Telegram alert: {e}")

    def run_all_checks(self) -> bool:
        """运行所有检查"""
        print("=" * 80)
        print(f"{'🏥 HEALTH CHECK REPORT':^80}")
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^80}")
        print("=" * 80)

        # 定义所有检查
        check_functions = [
            ("Process Running", self.check_process_running),
            ("Log Activity", self.check_log_activity),
            ("WebSocket Connection", self.check_websocket_connection),
            ("Recent Errors", self.check_recent_errors),
            ("Account Balance", self.check_account_balance),
            ("Position Health", self.check_position_health),
            ("Disk Space", self.check_disk_space),
        ]

        all_passed = True

        for check_name, check_func in check_functions:
            passed, message = check_func()
            self.checks.append((check_name, passed, message))

            status = "✅" if passed else "❌"
            print(f"{status} {check_name:<25} : {message}")

            if not passed:
                all_passed = False
                self.errors.append(f"{check_name}: {message}")

        print("=" * 80)

        # 总结
        if all_passed:
            print("✅ All checks passed - System is healthy")
        else:
            print(f"❌ {len(self.errors)} check(s) failed - System needs attention")

            # 发送告警
            if self.send_alert and self.errors:
                alert_msg = "Copy Trader Health Check Failed:\n\n"
                for error in self.errors:
                    alert_msg += f"❌ {error}\n"
                self.send_telegram_alert(alert_msg)

        if self.warnings:
            print(f"\n⚠️  {len(self.warnings)} warning(s):")
            for warning in self.warnings:
                print(f"   {warning}")

        print("=" * 80)
        print()

        return all_passed


def main():
    parser = argparse.ArgumentParser(description='Copy Trader Health Check')
    parser.add_argument('--alert', action='store_true', help='Send Telegram alert if checks fail')
    parser.add_argument('--continuous', action='store_true', help='Run continuously every N minutes')
    parser.add_argument('--interval', type=int, default=10, help='Check interval in minutes (default: 10)')

    args = parser.parse_args()

    if args.continuous:
        print(f"🔄 Running continuous health checks every {args.interval} minutes...")
        print("   Press Ctrl+C to stop\n")

        try:
            while True:
                checker = HealthChecker(send_alert=args.alert)
                checker.run_all_checks()
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\n👋 Health check stopped by user")
            sys.exit(0)
    else:
        checker = HealthChecker(send_alert=args.alert)
        success = checker.run_all_checks()
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
