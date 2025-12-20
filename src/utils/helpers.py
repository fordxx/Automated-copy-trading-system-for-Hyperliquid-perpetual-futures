"""Helper utilities for Hyperliquid Copy Trader."""
import logging
import os
from typing import Dict, Any
import yaml


def setup_logging(config: Dict[str, Any]):
    """设置日志配置。

    Args:
        config: 日志配置字典
    """
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO').upper())
    log_file = log_config.get('file', 'logs/copy_trader.log')

    # 创建日志目录
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 配置日志
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    # 设置第三方库日志级别
    logging.getLogger('hyperliquid').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)


def load_config(config_path: str) -> Dict[str, Any]:
    """加载YAML配置文件。

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def validate_config(config: Dict[str, Any]):
    """验证配置文件的有效性。

    Args:
        config: 配置字典

    Raises:
        ValueError: 配置无效时抛出
    """
    required_fields = [
        'target_address',
        'hyperliquid.account_address',
        'hyperliquid.private_key'
    ]

    for field in required_fields:
        keys = field.split('.')
        value = config
        for key in keys:
            value = value.get(key)
            if value is None:
                raise ValueError(f"Required config field missing: {field}")

    # 验证地址格式
    target_address = config['target_address']
    if not target_address.startswith('0x') or len(target_address) != 42:
        raise ValueError("Invalid target_address format")

    hl_config = config['hyperliquid']
    account_address = hl_config['account_address']
    if not account_address.startswith('0x') or len(account_address) != 42:
        raise ValueError("Invalid hyperliquid.account_address format")


def format_trade_summary(trade_data: Dict[str, Any]) -> str:
    """格式化交易摘要信息。

    Args:
        trade_data: 交易数据字典

    Returns:
        格式化的字符串
    """
    action = trade_data.get('action', 'unknown')
    coin = trade_data.get('coin', 'unknown')
    size = trade_data.get('size', 0)
    price = trade_data.get('price', 0)

    return f"{action.upper()} {size} {coin} @ ${price}"


def calculate_pnl_percentage(entry_price: float, current_price: float, is_long: bool) -> float:
    """计算盈亏百分比。

    Args:
        entry_price: 入场价格
        current_price: 当前价格
        is_long: 是否多头

    Returns:
        盈亏百分比
    """
    if entry_price == 0:
        return 0.0

    if is_long:
        return (current_price - entry_price) / entry_price
    else:
        return (entry_price - current_price) / entry_price


def safe_float_convert(value: Any, default: float = 0.0) -> float:
    """安全地将值转换为浮点数。

    Args:
        value: 要转换的值
        default: 默认值

    Returns:
        转换后的浮点数
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int_convert(value: Any, default: int = 0) -> int:
    """安全地将值转换为整数。

    Args:
        value: 要转换的值
        default: 默认值

    Returns:
        转换后的整数
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default