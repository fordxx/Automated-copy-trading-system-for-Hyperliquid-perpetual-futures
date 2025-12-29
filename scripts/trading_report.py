#!/usr/bin/env python3
"""
交易统计报表生成器

使用方法:
    python scripts/trading_report.py --period today
    python scripts/trading_report.py --period week
    python scripts/trading_report.py --period month
    python scripts/trading_report.py --custom 2025-12-20 2025-12-27
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from hyperliquid.info import Info
from hyperliquid.utils import constants

load_dotenv()


class TradingReport:
    """交易报表生成器"""

    def __init__(self):
        self.follower_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')
        base_url = constants.TESTNET_API_URL if os.getenv('HYPERLIQUID_ENV') == 'testnet' else constants.MAINNET_API_URL
        self.info = Info(base_url, skip_ws=True)

    def get_user_fills(self, start_time: int) -> List[Dict]:
        """获取用户成交记录"""
        try:
            user_fills = self.info.user_fills(self.follower_address)

            # 过滤时间范围
            filtered = []
            for fill in user_fills:
                fill_time = fill.get('time', 0)
                if fill_time >= start_time:
                    filtered.append(fill)

            return filtered
        except Exception as e:
            print(f"Error fetching fills: {e}")
            return []

    def parse_log_file(self, log_path: Path, start_time: datetime) -> Dict:
        """解析日志文件提取交易统计"""
        stats = {
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'skipped_trades': 0,
            'errors': 0,
            'warnings': 0,
            'coins_traded': set(),
            'total_volume': 0.0,
        }

        if not log_path.exists():
            return stats

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    # 解析时间戳
                    if line.startswith('2025-'):
                        try:
                            timestamp_str = line.split(' - ')[0]
                            log_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')

                            if log_time < start_time:
                                continue

                            # 统计不同类型的日志
                            if 'Trade executed' in line or 'EXECUTED' in line:
                                stats['successful_trades'] += 1
                                stats['total_trades'] += 1

                                # 提取币种
                                if 'coin=' in line:
                                    coin = line.split('coin=')[1].split()[0].strip(',')
                                    stats['coins_traded'].add(coin)

                            elif 'FAILED' in line or 'Trade failed' in line:
                                stats['failed_trades'] += 1
                                stats['total_trades'] += 1

                            elif 'SKIP' in line:
                                stats['skipped_trades'] += 1

                            elif 'ERROR' in line:
                                stats['errors'] += 1

                            elif 'WARNING' in line:
                                stats['warnings'] += 1

                        except (ValueError, IndexError):
                            continue

        except Exception as e:
            print(f"Error parsing log: {e}")

        stats['coins_traded'] = len(stats['coins_traded'])
        return stats

    def analyze_fills(self, fills: List[Dict]) -> Dict:
        """分析成交数据"""
        analysis = {
            'total_fills': len(fills),
            'total_volume': 0.0,
            'total_fees': 0.0,
            'coins': defaultdict(lambda: {
                'count': 0,
                'volume': 0.0,
                'fees': 0.0,
                'pnl': 0.0
            }),
            'by_side': {'buy': 0, 'sell': 0},
            'avg_fill_price': {},
        }

        for fill in fills:
            coin = fill.get('coin', 'UNKNOWN')
            px = float(fill.get('px', 0))
            sz = abs(float(fill.get('sz', 0)))
            side = fill.get('side', 'unknown')
            fee = float(fill.get('fee', 0))
            closed_pnl = float(fill.get('closedPnl', 0))

            volume = px * sz

            analysis['total_volume'] += volume
            analysis['total_fees'] += fee

            coin_stats = analysis['coins'][coin]
            coin_stats['count'] += 1
            coin_stats['volume'] += volume
            coin_stats['fees'] += fee
            coin_stats['pnl'] += closed_pnl

            if side in analysis['by_side']:
                analysis['by_side'][side] += 1

        return analysis

    def get_current_positions(self) -> Dict:
        """获取当前仓位"""
        try:
            user_state = self.info.user_state(self.follower_address)
            positions = user_state.get('assetPositions', [])

            total_pnl = 0.0
            total_notional = 0.0
            pos_count = 0

            for pos in positions:
                position = pos['position']
                unrealized_pnl = float(position.get('unrealizedPnl', 0))
                size = float(position.get('szi', 0))
                entry_px = float(position.get('entryPx', 0))

                total_pnl += unrealized_pnl
                total_notional += abs(size * entry_px)
                pos_count += 1

            account_value = float(user_state.get('marginSummary', {}).get('accountValue', 0))

            return {
                'position_count': pos_count,
                'total_unrealized_pnl': total_pnl,
                'total_notional': total_notional,
                'account_value': account_value
            }
        except Exception as e:
            print(f"Error getting positions: {e}")
            return {
                'position_count': 0,
                'total_unrealized_pnl': 0.0,
                'total_notional': 0.0,
                'account_value': 0.0
            }

    def generate_report(self, period: str = 'today', custom_start: str = None, custom_end: str = None):
        """生成报表"""
        # 确定时间范围
        now = datetime.now()

        if period == 'today':
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            title = "Today's Trading Report"
        elif period == 'week':
            start_time = now - timedelta(days=7)
            title = "Weekly Trading Report (Last 7 Days)"
        elif period == 'month':
            start_time = now - timedelta(days=30)
            title = "Monthly Trading Report (Last 30 Days)"
        elif custom_start and custom_end:
            start_time = datetime.strptime(custom_start, '%Y-%m-%d')
            end_time = datetime.strptime(custom_end, '%Y-%m-%d')
            title = f"Trading Report ({custom_start} to {custom_end})"
        else:
            start_time = now - timedelta(days=1)
            title = "Last 24 Hours Trading Report"

        print("=" * 100)
        print(f"{title:^100}")
        print(f"{'Generated at: ' + now.strftime('%Y-%m-%d %H:%M:%S'):^100}")
        print("=" * 100)

        # 日志统计
        log_path = Path(__file__).parent.parent / 'logs' / 'copy_trader.log'
        log_stats = self.parse_log_file(log_path, start_time)

        print(f"\n{'📊 TRADING ACTIVITY':^100}")
        print("-" * 100)
        print(f"Total Trades     : {log_stats['total_trades']}")
        print(f"  ✅ Successful  : {log_stats['successful_trades']}")
        print(f"  ❌ Failed      : {log_stats['failed_trades']}")
        print(f"  ⏭️  Skipped    : {log_stats['skipped_trades']}")
        print(f"Coins Traded     : {log_stats['coins_traded']}")
        print(f"Warnings         : {log_stats['warnings']}")
        print(f"Errors           : {log_stats['errors']}")

        # 成交分析
        start_timestamp = int(start_time.timestamp() * 1000)
        fills = self.get_user_fills(start_timestamp)
        fill_analysis = self.analyze_fills(fills)

        print(f"\n{'💰 FILL ANALYSIS':^100}")
        print("-" * 100)
        print(f"Total Fills      : {fill_analysis['total_fills']}")
        print(f"Total Volume     : ${fill_analysis['total_volume']:,.2f}")
        print(f"Total Fees       : ${fill_analysis['total_fees']:,.2f}")
        print(f"Buy Fills        : {fill_analysis['by_side']['buy']}")
        print(f"Sell Fills       : {fill_analysis['by_side']['sell']}")

        # 各币种统计
        if fill_analysis['coins']:
            print(f"\n{'📈 BY COIN':^100}")
            print("-" * 100)
            print(f"{'Coin':<10} {'Fills':>10} {'Volume':>18} {'Fees':>15} {'Closed PnL':>18}")
            print("-" * 100)

            sorted_coins = sorted(
                fill_analysis['coins'].items(),
                key=lambda x: x[1]['volume'],
                reverse=True
            )[:10]

            for coin, stats in sorted_coins:
                pnl_emoji = '🟢' if stats['pnl'] >= 0 else '🔴'
                print(f"{coin:<10} {stats['count']:>10} ${stats['volume']:>17,.2f} "
                      f"${stats['fees']:>14,.2f} {pnl_emoji} ${stats['pnl']:>15,.2f}")

        # 当前仓位
        current_pos = self.get_current_positions()

        print(f"\n{'💼 CURRENT POSITIONS':^100}")
        print("-" * 100)
        print(f"Open Positions   : {current_pos['position_count']}")
        print(f"Total Notional   : ${current_pos['total_notional']:,.2f}")
        print(f"Unrealized PnL   : ${current_pos['total_unrealized_pnl']:,.2f}")
        print(f"Account Value    : ${current_pos['account_value']:,.2f}")

        # 性能指标
        if fill_analysis['total_fills'] > 0:
            avg_volume_per_fill = fill_analysis['total_volume'] / fill_analysis['total_fills']
            avg_fee_per_fill = fill_analysis['total_fees'] / fill_analysis['total_fills']
            fee_rate = (fill_analysis['total_fees'] / fill_analysis['total_volume'] * 100) if fill_analysis['total_volume'] > 0 else 0

            print(f"\n{'📉 PERFORMANCE METRICS':^100}")
            print("-" * 100)
            print(f"Avg Volume/Fill  : ${avg_volume_per_fill:,.2f}")
            print(f"Avg Fee/Fill     : ${avg_fee_per_fill:,.2f}")
            print(f"Fee Rate         : {fee_rate:.4f}%")

            if log_stats['total_trades'] > 0:
                success_rate = (log_stats['successful_trades'] / log_stats['total_trades']) * 100
                print(f"Success Rate     : {success_rate:.2f}%")

        print(f"\n{'=' * 100}\n")


def main():
    parser = argparse.ArgumentParser(description='Generate Trading Report')
    parser.add_argument('--period', choices=['today', 'week', 'month'], default='today',
                        help='Report period (default: today)')
    parser.add_argument('--custom', nargs=2, metavar=('START', 'END'),
                        help='Custom period (format: YYYY-MM-DD YYYY-MM-DD)')

    args = parser.parse_args()

    report = TradingReport()

    if args.custom:
        report.generate_report(custom_start=args.custom[0], custom_end=args.custom[1])
    else:
        report.generate_report(period=args.period)


if __name__ == '__main__':
    main()
