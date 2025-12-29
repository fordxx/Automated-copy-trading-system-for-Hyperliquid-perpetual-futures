#!/usr/bin/env python3
"""
实时监控面板 - 显示跟单机器人运行状态

使用方法:
    python scripts/monitor_dashboard.py
    python scripts/monitor_dashboard.py --compact  # 紧凑模式
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.utils import constants

# 加载环境变量
load_dotenv()


class MonitorDashboard:
    """监控面板"""

    def __init__(self, compact=False):
        self.compact = compact
        self.target_address = os.getenv('TARGET_ADDRESS')
        self.follower_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')
        self.copy_ratio = float(os.getenv('COPY_RATIO', '0.2'))

        # 初始化API
        base_url = constants.TESTNET_API_URL if os.getenv('HYPERLIQUID_ENV') == 'testnet' else constants.MAINNET_API_URL
        self.info = Info(base_url, skip_ws=True)

        # 统计数据
        self.start_time = datetime.now()
        self.refresh_count = 0

    def clear_screen(self):
        """清屏"""
        os.system('clear' if os.name != 'nt' else 'cls')

    def get_positions(self, address):
        """获取仓位信息"""
        try:
            user_state = self.info.user_state(address)
            positions = user_state.get('assetPositions', [])

            pos_list = []
            total_unrealized_pnl = 0.0
            total_notional = 0.0

            for pos in positions:
                position = pos['position']
                coin = position['coin']
                size = float(position['szi'])
                entry_px = float(position['entryPx'])
                unrealized_pnl = float(position['unrealizedPnl'])
                notional = abs(size * entry_px)

                pos_list.append({
                    'coin': coin,
                    'size': size,
                    'entry_px': entry_px,
                    'unrealized_pnl': unrealized_pnl,
                    'notional': notional
                })

                total_unrealized_pnl += unrealized_pnl
                total_notional += notional

            return {
                'positions': pos_list,
                'count': len(pos_list),
                'total_pnl': total_unrealized_pnl,
                'total_notional': total_notional,
                'account_value': float(user_state.get('marginSummary', {}).get('accountValue', 0))
            }
        except Exception as e:
            return {
                'positions': [],
                'count': 0,
                'total_pnl': 0,
                'total_notional': 0,
                'account_value': 0,
                'error': str(e)
            }

    def get_process_info(self):
        """获取进程信息"""
        try:
            pid_file = Path(__file__).parent.parent / 'logs' / 'copy_trader.pid'
            if pid_file.exists():
                with open(pid_file, 'r') as f:
                    pid = f.read().strip()

                # 检查进程是否存在 - 使用多种方法
                import subprocess

                # 方法1: 尝试使用ps命令
                try:
                    result = subprocess.run(
                        ['ps', '-p', pid, '-o', 'pid,etime,rss,%cpu'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )

                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        if len(lines) > 1:
                            parts = lines[1].split()
                            # 解析字段,容错处理
                            try:
                                memory_mb = int(parts[2]) / 1024 if len(parts) > 2 and parts[2].isdigit() else 0
                                cpu_percent = float(parts[3]) if len(parts) > 3 and parts[3].replace('.', '').isdigit() else 0.0
                            except (ValueError, IndexError):
                                memory_mb = 0
                                cpu_percent = 0.0

                            return {
                                'pid': parts[0] if len(parts) > 0 else pid,
                                'uptime': parts[1] if len(parts) > 1 else 'unknown',
                                'memory_mb': memory_mb,
                                'cpu_percent': cpu_percent,
                                'running': True
                            }
                except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                    pass

                # 方法2: 检查 /proc/{pid} 目录是否存在
                try:
                    proc_path = Path(f'/proc/{pid}')
                    if proc_path.exists():
                        # 进程存在,尝试读取状态
                        try:
                            with open(proc_path / 'status', 'r') as f:
                                status_lines = f.readlines()

                            # 从status文件提取信息
                            return {
                                'pid': pid,
                                'uptime': 'running',
                                'memory_mb': 0,  # 简化版本不读取内存
                                'cpu_percent': 0.0,
                                'running': True
                            }
                        except:
                            # /proc存在但无法读取,至少说明进程在运行
                            return {
                                'pid': pid,
                                'uptime': 'running',
                                'memory_mb': 0,
                                'cpu_percent': 0.0,
                                'running': True
                            }
                except:
                    pass

            return {'running': False}
        except Exception as e:
            return {'running': False, 'error': str(e)}

    def get_log_stats(self):
        """获取日志统计"""
        try:
            log_file = Path(__file__).parent.parent / 'logs' / 'copy_trader.log'
            if not log_file.exists():
                return {'trades': 0, 'errors': 0, 'warnings': 0}

            # 读取最近1000行
            with open(log_file, 'r') as f:
                lines = f.readlines()[-1000:]

            trades = sum(1 for line in lines if 'Trade executed' in line or 'EXECUTED' in line)
            errors = sum(1 for line in lines if 'ERROR' in line)
            warnings = sum(1 for line in lines if 'WARNING' in line)

            return {
                'trades': trades,
                'errors': errors,
                'warnings': warnings,
                'total_lines': len(lines)
            }
        except Exception as e:
            return {'trades': 0, 'errors': 0, 'warnings': 0, 'error': str(e)}

    def calculate_ratio_accuracy(self, leader_pos, follower_pos):
        """计算仓位比例准确度"""
        if not leader_pos or not follower_pos:
            return []

        leader_dict = {p['coin']: p['size'] for p in leader_pos}
        follower_dict = {p['coin']: p['size'] for p in follower_pos}

        all_coins = set(leader_dict.keys()) | set(follower_dict.keys())

        ratios = []
        for coin in all_coins:
            leader_size = leader_dict.get(coin, 0)
            follower_size = follower_dict.get(coin, 0)

            if leader_size == 0:
                actual_ratio = 0 if follower_size == 0 else 100
            else:
                actual_ratio = (follower_size / leader_size) * 100

            expected_ratio = self.copy_ratio * 100
            deviation = abs(actual_ratio - expected_ratio)

            ratios.append({
                'coin': coin,
                'leader_size': leader_size,
                'follower_size': follower_size,
                'actual_ratio': actual_ratio,
                'expected_ratio': expected_ratio,
                'deviation': deviation
            })

        return sorted(ratios, key=lambda x: x['deviation'], reverse=True)

    def render_compact(self, leader_data, follower_data, process_info, log_stats):
        """紧凑模式渲染"""
        print(f"\n{'='*80}")
        print(f"🤖 Hyperliquid Copy Trader Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")

        # 进程状态
        if process_info['running']:
            print(f"✅ Running | PID: {process_info['pid']} | Uptime: {process_info['uptime']} | "
                  f"Mem: {process_info['memory_mb']:.1f}MB | CPU: {process_info['cpu_percent']}%")
        else:
            print(f"❌ Not Running")

        # 账户状态
        print(f"\n📊 Leader: {self.target_address[:10]}... | "
              f"Positions: {leader_data['count']} | "
              f"PnL: ${leader_data['total_pnl']:.2f} | "
              f"Notional: ${leader_data['total_notional']:.2f}")

        print(f"👤 Follower: {self.follower_address[:10]}... | "
              f"Positions: {follower_data['count']} | "
              f"PnL: ${follower_data['total_pnl']:.2f} | "
              f"Notional: ${follower_data['total_notional']:.2f} | "
              f"Value: ${follower_data['account_value']:.2f}")

        # 日志统计
        print(f"\n📝 Recent Activity: Trades: {log_stats['trades']} | "
              f"Warnings: {log_stats['warnings']} | "
              f"Errors: {log_stats['errors']}")

        # 仓位比例准确度
        ratios = self.calculate_ratio_accuracy(leader_data['positions'], follower_data['positions'])
        if ratios:
            top_deviations = [r for r in ratios if r['deviation'] > 5][:3]
            if top_deviations:
                print(f"\n⚠️  Top Ratio Deviations:")
                for r in top_deviations:
                    print(f"   {r['coin']:8s}: {r['actual_ratio']:6.2f}% (expected {r['expected_ratio']:.1f}%, off by {r['deviation']:.1f}%)")

    def render_full(self, leader_data, follower_data, process_info, log_stats):
        """完整模式渲染"""
        self.clear_screen()

        print("=" * 100)
        print(f"{'🤖 HYPERLIQUID COPY TRADER MONITORING DASHBOARD':^100}")
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^100}")
        print("=" * 100)

        # 进程信息
        print(f"\n{'📡 PROCESS STATUS':^100}")
        print("-" * 100)
        if process_info['running']:
            print(f"Status      : ✅ RUNNING")
            print(f"PID         : {process_info['pid']}")
            print(f"Uptime      : {process_info['uptime']}")
            print(f"Memory      : {process_info['memory_mb']:.1f} MB")
            print(f"CPU         : {process_info['cpu_percent']}%")
        else:
            print(f"Status      : ❌ NOT RUNNING")

        # Leader账户
        print(f"\n{'📊 LEADER ACCOUNT':^100}")
        print("-" * 100)
        print(f"Address     : {self.target_address}")
        print(f"Positions   : {leader_data['count']}")
        print(f"Unrealized  : ${leader_data['total_pnl']:.2f}")
        print(f"Notional    : ${leader_data['total_notional']:.2f}")

        # Follower账户
        print(f"\n{'👤 FOLLOWER ACCOUNT':^100}")
        print("-" * 100)
        print(f"Address     : {self.follower_address}")
        print(f"Positions   : {follower_data['count']}")
        print(f"Unrealized  : ${follower_data['total_pnl']:.2f}")
        print(f"Notional    : ${follower_data['total_notional']:.2f}")
        print(f"Account Val : ${follower_data['account_value']:.2f}")
        print(f"Copy Ratio  : {self.copy_ratio * 100:.1f}%")

        # 仓位详情
        if follower_data['positions']:
            print(f"\n{'💼 POSITIONS':^100}")
            print("-" * 100)
            print(f"{'Coin':<10} {'Size':>15} {'Entry':>12} {'Unrealized PnL':>18} {'Notional':>15}")
            print("-" * 100)

            for pos in sorted(follower_data['positions'], key=lambda x: abs(x['notional']), reverse=True)[:10]:
                pnl_color = '🟢' if pos['unrealized_pnl'] >= 0 else '🔴'
                print(f"{pos['coin']:<10} {pos['size']:>15.4f} ${pos['entry_px']:>11.6f} "
                      f"{pnl_color} ${pos['unrealized_pnl']:>15.2f} ${pos['notional']:>14.2f}")

        # 比例准确度
        ratios = self.calculate_ratio_accuracy(leader_data['positions'], follower_data['positions'])
        if ratios:
            top_deviations = [r for r in ratios if r['deviation'] > 2][:10]
            if top_deviations:
                print(f"\n{'⚖️  RATIO ACCURACY (Top Deviations)':^100}")
                print("-" * 100)
                print(f"{'Coin':<10} {'Leader Size':>15} {'Follower Size':>15} {'Actual%':>10} {'Expected%':>10} {'Dev%':>10}")
                print("-" * 100)
                for r in top_deviations:
                    status = '✅' if r['deviation'] < 5 else '⚠️' if r['deviation'] < 10 else '❌'
                    print(f"{status} {r['coin']:<8} {r['leader_size']:>15.2f} {r['follower_size']:>15.2f} "
                          f"{r['actual_ratio']:>10.2f} {r['expected_ratio']:>10.1f} {r['deviation']:>10.1f}")

        # 日志统计
        print(f"\n{'📝 LOG STATISTICS (Last 1000 lines)':^100}")
        print("-" * 100)
        print(f"Trades      : {log_stats['trades']}")
        print(f"Warnings    : {log_stats['warnings']}")
        print(f"Errors      : {log_stats['errors']}")

        print(f"\n{'─' * 100}")
        print(f"{'Refresh count: ' + str(self.refresh_count) + ' | Press Ctrl+C to exit':^100}")
        print(f"{'─' * 100}\n")

    def run(self, interval=5):
        """运行监控"""
        print("🚀 Starting monitoring dashboard...")
        print(f"📊 Refresh interval: {interval}s")
        print(f"{'─' * 100}\n")

        try:
            while True:
                self.refresh_count += 1

                # 获取数据
                leader_data = self.get_positions(self.target_address)
                follower_data = self.get_positions(self.follower_address)
                process_info = self.get_process_info()
                log_stats = self.get_log_stats()

                # 渲染
                if self.compact:
                    self.render_compact(leader_data, follower_data, process_info, log_stats)
                else:
                    self.render_full(leader_data, follower_data, process_info, log_stats)

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped by user")
            sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='Copy Trader Monitoring Dashboard')
    parser.add_argument('--compact', action='store_true', help='Compact mode (no clear screen)')
    parser.add_argument('--interval', type=int, default=5, help='Refresh interval in seconds (default: 5)')

    args = parser.parse_args()

    dashboard = MonitorDashboard(compact=args.compact)
    dashboard.run(interval=args.interval)


if __name__ == '__main__':
    main()
