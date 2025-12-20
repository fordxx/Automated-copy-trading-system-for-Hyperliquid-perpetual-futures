#!/usr/bin/env python3
"""Hyperliquid Copy Trader Runner Script.

启动自动跟单交易器。
"""
import asyncio
import logging
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.copy_trader import HyperliquidCopyTrader
from src.utils.helpers import setup_logging, validate_config, load_config


def main():
    """主函数。"""
    # 配置路径
    config_path = project_root / "config" / "config.yaml"

    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        print("Please copy config/config.yaml and update your settings.")
        sys.exit(1)

    try:
        # 加载配置
        config = load_config(str(config_path))

        # 验证配置
        validate_config(config)

        # 设置日志
        setup_logging(config)

        logger = logging.getLogger(__name__)
        logger.info("🚀 Starting Hyperliquid Copy Trader")

        # 创建交易器实例
        trader = HyperliquidCopyTrader(str(config_path))

        # 运行交易器
        asyncio.run(trader.start())

    except KeyboardInterrupt:
        print("\n🛑 Received keyboard interrupt, stopping...")
    except Exception as e:
        print(f"❌ Error: {e}")
        logging.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()