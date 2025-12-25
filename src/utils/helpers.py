"""Helper utilities for Hyperliquid Copy Trader."""
import logging
import os
import re
from typing import Dict, Any
import yaml


class SecretRedactingFilter(logging.Filter):
    """Redacts common secret patterns from log messages."""

    _re_private_key = re.compile(r"0x[a-fA-F0-9]{64}")
    _re_tg_token = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
    _re_env_assignments = re.compile(
        r"\b(HYPERLIQUID_PRIVATE_KEY|TELEGRAM_BOT_TOKEN)=[^\s]+",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Get the formatted message (after args interpolation)
            msg = record.getMessage()
        except Exception:
            return True

        sanitized = msg
        sanitized = self._re_private_key.sub("0x***REDACTED***", sanitized)
        sanitized = self._re_tg_token.sub("***REDACTED_TG_TOKEN***", sanitized)
        sanitized = self._re_env_assignments.sub(lambda m: f"{m.group(1)}=***REDACTED***", sanitized)

        if sanitized != msg:
            # Replace the message with sanitized version and clear args
            # to prevent double formatting
            record.msg = sanitized
            record.args = ()
            # Also sanitize the raw msg in case it's used elsewhere
            if hasattr(record, '_original_msg'):
                record._original_msg = sanitized
        return True


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

    # Redact secrets from any accidental log output.
    redactor = SecretRedactingFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(redactor)
    for handler in root_logger.handlers:
        handler.addFilter(redactor)

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

    missing_fields = []
    for field in required_fields:
        keys = field.split('.')
        value = config
        for key in keys:
            value = value.get(key)
            if value is None:
                missing_fields.append(field)
                break

    if missing_fields:
        raise ValueError(f"Required config fields missing: {', '.join(missing_fields)}")

    # 验证目标地址格式
    target_address = config.get('target_address', '')
    if not isinstance(target_address, str) or (not target_address.startswith('0x')) or len(target_address) != 42:
        raise ValueError("Invalid target_address format (must be 42-character hex starting with 0x)")

    # 验证 Hyperliquid 配置
    hl_config = config['hyperliquid']
    account_address = hl_config['account_address']
    if not account_address.startswith('0x') or len(account_address) != 42:
        raise ValueError("Invalid hyperliquid.account_address format (must be 42-character hex starting with 0x)")

    # 验证私钥格式 (64字符的十六进制)
    private_key = hl_config['private_key']
    if not private_key.startswith('0x') or len(private_key) != 66:
        raise ValueError("Invalid hyperliquid.private_key format (must be 66-character hex starting with 0x)")

    # 验证排除地址格式
    exclude_addresses = config.get('exclude_addresses', [])
    for addr in exclude_addresses:
        if addr and (not addr.startswith('0x') or len(addr) != 42):
            raise ValueError(f"Invalid exclude_address format: {addr} (must be 42-character hex starting with 0x)")

    # 验证Telegram配置（如果启用）
    tg_config = config.get('telegram', {})
    if tg_config.get('enabled', False):
        bot_token = tg_config.get('bot_token', '')
        chat_id = tg_config.get('chat_id', '')
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token and chat_id are required when telegram is enabled")

    # 验证数值范围
    ct_config = config.get('copy_trading', {})
    copy_ratio = ct_config.get('copy_ratio', 0.1)
    if not 0 < copy_ratio <= 1.0:
        raise ValueError("copy_ratio must be between 0 and 1.0")

    max_position = ct_config.get('max_position_size', 1.0)
    if max_position <= 0:
        raise ValueError("max_position_size must be greater than 0")

    min_trade = ct_config.get('min_trade_size', 0.01)
    if min_trade <= 0:
        raise ValueError("min_trade_size must be greater than 0")

    max_leverage = ct_config.get('max_leverage', 5)
    if max_leverage < 1 or max_leverage > 50:
        raise ValueError("max_leverage must be between 1 and 50")

    # 验证监控配置
    mon_config = config.get('monitoring', {})

    poll_interval = float(mon_config.get('poll_interval', 30))
    if poll_interval < 0.5:
        raise ValueError("poll_interval must be at least 0.5 seconds")
    if poll_interval < 1:
        print(f"⚠️  Warning: Ultra-high frequency monitoring enabled ({poll_interval}s). This may cause high API usage.")

    # min_api_interval 单位为毫秒(ms)，用于限制 REST API 调用频率
    min_api_interval = mon_config.get('min_api_interval', 1000)
    try:
        min_api_interval = int(min_api_interval)
    except Exception:
        raise ValueError("min_api_interval must be an int (milliseconds)")
    if min_api_interval < 1000:
        print(f"⚠️  Warning: min_api_interval is very low ({min_api_interval}ms). This may trigger rate limits.")

    print("✅ Configuration validation passed")


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