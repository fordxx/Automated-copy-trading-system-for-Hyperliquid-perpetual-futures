#!/usr/bin/env python3
"""Hyperliquid Copy Trader Runner Script.

启动自动跟单交易器。
支持环境变量和配置文件两种配置方式。
"""
import asyncio
import logging
import sys
import os
import argparse
from pathlib import Path
import atexit

import fcntl

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.copy_trader import HyperliquidCopyTrader
from src.utils.helpers import setup_logging, validate_config, load_config


def _acquire_single_instance_lock(project_root: Path) -> int:
    """Ensure only one copy-trader instance runs at a time.

    Uses an advisory file lock on logs/copy_trader.lock.
    Also writes logs/copy_trader.pid for operational visibility.
    """
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    lock_path = logs_dir / "copy_trader.lock"
    pid_path = logs_dir / "copy_trader.pid"

    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        existing_pid = None
        try:
            existing_pid = pid_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        msg = "❌ Another copy-trader instance is already running."
        if existing_pid:
            msg += f" (pid={existing_pid})"
        msg += f"\nLock file: {lock_path}"
        print(msg)
        os.close(lock_fd)
        sys.exit(2)

    # We hold the lock; record our PID.
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup() -> None:
        try:
            pid_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(lock_fd)
        except Exception:
            pass

    atexit.register(_cleanup)
    return lock_fd


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description='Hyperliquid Copy Trader')
    parser.add_argument('--config', '-c', type=str,
                       help='Path to config file (optional, will use env vars if not provided)')
    parser.add_argument('--env', action='store_true',
                       help='Force use environment variables only (ignore config file)')

    args = parser.parse_args()

    # Single-instance guard (prevents duplicate trading).
    _acquire_single_instance_lock(project_root)

    try:
        config_path = None
        config = {}

        # Determine configuration source
        if args.env:
            # Use environment variables only
            print("🔧 Using environment variables for configuration")
            config_path = None
        elif args.config:
            # Use specified config file
            config_path = Path(args.config)
            if not config_path.exists():
                print(f"❌ Config file not found: {config_path}")
                sys.exit(1)
            print(f"🔧 Using config file: {config_path}")
        else:
            # Try to use default config file, fallback to env vars
            default_config = project_root / "config" / "config.yaml"
            if default_config.exists():
                config_path = default_config
                print(f"🔧 Using default config file: {config_path}")
            else:
                print("🔧 No config file found, using environment variables")

        # Load configuration
        if config_path:
            config = load_config(str(config_path))

        # Create trader instance (will load env vars automatically)
        trader = HyperliquidCopyTrader(str(config_path) if config_path else None)

        # Validate configuration from the loaded config
        validate_config(trader.config)

        # Setup logging
        setup_logging(trader.config)

        logger = logging.getLogger(__name__)
        logger.info("🚀 Starting Hyperliquid Copy Trader")

        # Show configuration summary
        print_config_summary(trader.config)

        # Run trader
        asyncio.run(trader.start())

    except KeyboardInterrupt:
        print("\n🛑 Received keyboard interrupt, stopping...")
    except Exception as e:
        print(f"❌ Error: {e}")
        logging.exception("Fatal error")
        sys.exit(1)


def print_config_summary(config):
    """打印配置摘要。"""
    print("\n" + "="*50)
    print("📋 CONFIGURATION SUMMARY")
    print("="*50)

    # Target
    target = config.get('target_address', 'Not set')
    print(f"🎯 Target Address: {target[:10]}...{target[-8:] if len(target) > 18 else target}")

    # Exclude addresses
    exclude = config.get('exclude_addresses', [])
    if exclude:
        print(f"🚫 Exclude Addresses: {len(exclude)} address(es)")
    else:
        print("🚫 Exclude Addresses: None")

    # Hyperliquid
    hl = config.get('hyperliquid', {})
    account = hl.get('account_address', 'Not set')
    print(f"🏦 Account Address: {account[:10]}...{account[-8:] if len(account) > 18 else account}")
    print(f"🌐 Network: {'Testnet' if hl.get('use_testnet', False) else 'Mainnet'}")

    # Copy trading
    ct = config.get('copy_trading', {})
    print(f"📊 Copy Ratio: {ct.get('copy_ratio', 0.1) * 100:.1f}%")
    print(f"📏 Max Position: {ct.get('max_position_size', 1.0)} contracts")

    # Telegram
    tg = config.get('telegram', {})
    if tg.get('enabled', False):
        print("📱 Telegram Notifications: Enabled")
    else:
        print("📱 Telegram Notifications: Disabled")

    print("="*50 + "\n")


if __name__ == "__main__":
    main()