#!/usr/bin/env python3
"""清理超过指定天数的旧日志文件"""

import os
import time
import argparse
from pathlib import Path


def clean_old_logs(log_dir: str, days: int = 7, dry_run: bool = False):
    """清理旧日志文件
    
    Args:
        log_dir: 日志目录路径
        days: 保留天数
        dry_run: 仅显示将删除的文件，不实际删除
    """
    log_path = Path(log_dir)
    if not log_path.exists():
        print(f"日志目录不存在: {log_dir}")
        return
    
    current_time = time.time()
    cutoff_time = current_time - (days * 86400)  # 86400秒 = 1天
    
    deleted_count = 0
    deleted_size = 0
    
    # 查找所有日志文件（包括轮换的日志）
    log_patterns = ['*.log', '*.log.*']
    
    for pattern in log_patterns:
        for log_file in log_path.glob(pattern):
            # 跳过当前正在使用的主日志文件
            if log_file.name == 'copy_trader.log' or log_file.name == 'service_stdout.log':
                continue
                
            # 跳过pid和lock文件
            if log_file.suffix in ['.pid', '.lock']:
                continue
            
            try:
                file_mtime = log_file.stat().st_mtime
                file_size = log_file.stat().st_size
                
                if file_mtime < cutoff_time:
                    file_age_days = (current_time - file_mtime) / 86400
                    size_mb = file_size / (1024 * 1024)
                    
                    if dry_run:
                        print(f"[DRY RUN] 将删除: {log_file.name} "
                              f"(年龄: {file_age_days:.1f}天, 大小: {size_mb:.2f}MB)")
                    else:
                        print(f"删除: {log_file.name} "
                              f"(年龄: {file_age_days:.1f}天, 大小: {size_mb:.2f}MB)")
                        log_file.unlink()
                    
                    deleted_count += 1
                    deleted_size += file_size
                    
            except Exception as e:
                print(f"处理文件 {log_file.name} 时出错: {e}")
    
    if deleted_count > 0:
        total_mb = deleted_size / (1024 * 1024)
        action = "将释放" if dry_run else "已释放"
        print(f"\n{'=' * 60}")
        print(f"总计: {deleted_count} 个文件, {action} {total_mb:.2f}MB 空间")
    else:
        print(f"\n没有找到超过 {days} 天的旧日志文件")


def main():
    parser = argparse.ArgumentParser(description='清理旧日志文件')
    parser.add_argument('--log-dir', default='logs',
                        help='日志目录路径 (默认: logs)')
    parser.add_argument('--days', type=int, default=7,
                        help='保留天数 (默认: 7)')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅显示将删除的文件，不实际删除')
    
    args = parser.parse_args()
    
    print(f"清理日志配置:")
    print(f"  日志目录: {args.log_dir}")
    print(f"  保留天数: {args.days}")
    print(f"  模式: {'预览模式' if args.dry_run else '执行模式'}")
    print(f"{'=' * 60}\n")
    
    clean_old_logs(args.log_dir, args.days, args.dry_run)


if __name__ == '__main__':
    main()
