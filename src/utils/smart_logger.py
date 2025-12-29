"""
智能日志过滤器 - 减少重复日志噪音

功能:
1. 相同消息只在首次和变化时输出
2. 周期性消息降频输出
3. 计数器累积相同消息
"""

import time
import logging
import hashlib
from typing import Dict, Optional
from collections import defaultdict


class SmartLogFilter(logging.Filter):
    """智能日志过滤器 - 减少重复消息"""

    def __init__(self, name='', throttle_seconds=60):
        super().__init__(name)
        self.throttle_seconds = throttle_seconds
        self._last_log_time: Dict[str, float] = {}
        self._message_counts: Dict[str, int] = defaultdict(int)
        self._last_flushed: Dict[str, float] = {}

    def _get_message_key(self, record: logging.LogRecord) -> str:
        """生成消息的唯一键"""
        # 提取消息模板(去除动态数据)
        msg = record.getMessage()

        # 针对不同类型的消息使用不同的键
        if 'WebSocket Stats:' in msg:
            return 'ws_stats'
        elif 'Batcher Stats:' in msg:
            return 'batcher_stats'
        elif 'Status:' in msg and 'positions' in msg:
            return 'position_status'
        elif 'Position sync:' in msg and 'noop' in msg:
            return 'position_sync_noop'
        elif 'szDecimals for' in msg:
            # 对szDecimals消息,每个币种单独计数
            if "'" in msg:
                coin = msg.split("'")[1]
                return f'szDecimals_{coin}'
            return 'szDecimals'
        else:
            # 其他消息用内容哈希
            return hashlib.md5(msg.encode()).hexdigest()[:16]

    def filter(self, record: logging.LogRecord) -> bool:
        """过滤重复消息"""
        # ERROR和WARNING级别总是通过
        if record.levelno >= logging.WARNING:
            return True

        # 重要消息总是通过
        msg = record.getMessage()
        important_keywords = [
            'Trade executed',
            'EXECUTED',
            'FAILED',
            'error',
            'Error',
            'Starting',
            'Stopping',
            'Connected',
            'Disconnected',
            'Subscription',
            'catch-up',
            'Catch-up'
        ]

        if any(kw in msg for kw in important_keywords):
            return True

        # 生成消息键
        msg_key = self._get_message_key(record)
        current_time = time.time()

        # 检查是否需要节流
        last_time = self._last_log_time.get(msg_key, 0)
        time_diff = current_time - last_time

        if time_diff < self.throttle_seconds:
            # 在节流期内,增加计数但不输出
            self._message_counts[msg_key] += 1
            return False
        else:
            # 节流期已过,输出消息
            count = self._message_counts.get(msg_key, 0)

            if count > 0:
                # 如果有被抑制的消息,在日志中附加计数
                suppressed_msg = f" (suppressed {count} similar messages in last {int(time_diff)}s)"
                record.msg = record.msg + suppressed_msg
                self._message_counts[msg_key] = 0

            self._last_log_time[msg_key] = current_time
            return True


class ChangeDetectionFilter(logging.Filter):
    """变化检测过滤器 - 只在值变化时输出"""

    def __init__(self, name=''):
        super().__init__(name)
        self._last_values: Dict[str, str] = {}

    def _extract_value(self, msg: str, pattern: str) -> Optional[str]:
        """从消息中提取值"""
        if pattern in msg:
            # 提取关键数值
            if 'positions' in msg and 'PnL' in msg:
                # "Status: 1 positions, Total PnL: $697.13"
                parts = msg.split(',')
                return ','.join(parts)  # 返回完整状态作为值
        return None

    def filter(self, record: logging.LogRecord) -> bool:
        """只在值变化时通过"""
        msg = record.getMessage()

        # 只处理状态消息
        if 'Status:' in msg and 'positions' in msg:
            value = self._extract_value(msg, 'Status:')
            if value:
                msg_key = 'position_status'
                last_value = self._last_values.get(msg_key)

                if value == last_value:
                    # 值未变化,过滤掉
                    return False
                else:
                    # 值变化了,更新并通过
                    self._last_values[msg_key] = value
                    return True

        # 其他消息默认通过
        return True


def setup_smart_logging(logger: logging.Logger, throttle_seconds: int = 60, enable_change_detection: bool = True):
    """为logger设置智能过滤"""
    # 添加节流过滤器
    throttle_filter = SmartLogFilter(throttle_seconds=throttle_seconds)
    logger.addFilter(throttle_filter)

    # 添加变化检测过滤器
    if enable_change_detection:
        change_filter = ChangeDetectionFilter()
        logger.addFilter(change_filter)

    return logger
