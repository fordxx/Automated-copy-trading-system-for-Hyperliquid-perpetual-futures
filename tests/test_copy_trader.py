"""Tests for Hyperliquid Copy Trader."""
import unittest
from unittest.mock import Mock, patch

from src.trade_monitor import TradeMonitor, MonitoredTrade, TradeAction
from src.position_manager import PositionManager, Position


class TestTradeMonitor(unittest.IsolatedAsyncioTestCase):
    """Test cases for TradeMonitor."""

    def setUp(self):
        self.monitor = TradeMonitor("0x1234567890123456789012345678901234567890", use_testnet=True)

    @patch('src.trade_monitor.Info')
    async def test_get_recent_trades(self, mock_info_class):
        """Test getting recent trades."""
        # Mock the info client
        mock_info = Mock()
        mock_info_class.return_value = mock_info
        self.monitor.info_client = mock_info

        # Mock user fills response
        fill_time_ms = self.monitor.last_check_timestamp + 1
        mock_fills = [
            {
                "coin": "BTC",
                "sz": "0.1",
                "px": "50000",
                "time": fill_time_ms,
                "hash": "0xabc123",
                "side": "B",
                "leverage": "5"
            }
        ]
        mock_info.user_fills.return_value = mock_fills

        # Test
        trades = await self.monitor.get_recent_trades()

        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade.action, TradeAction.OPEN_LONG)
        self.assertEqual(trade.coin, "BTC")
        self.assertEqual(trade.size, 0.1)
        self.assertEqual(trade.price, 50000.0)


class TestPositionManager(unittest.IsolatedAsyncioTestCase):
    """Test cases for PositionManager."""

    def setUp(self):
        self.exchange_mock = Mock()
        self.info_mock = Mock()
        self.manager = PositionManager(self.exchange_mock, self.info_mock)

    def test_position_properties(self):
        """Test position properties."""
        long_pos = Position("BTC", 0.1, 50000, 5)
        short_pos = Position("ETH", -0.2, 3000, 3)

        self.assertTrue(long_pos.is_long)
        self.assertFalse(long_pos.is_short)

        self.assertFalse(short_pos.is_long)
        self.assertTrue(short_pos.is_short)

    @patch('src.position_manager.Info')
    async def test_update_positions(self, mock_info_class):
        """Test updating positions."""
        # Mock user state response
        mock_user_state = {
            "assetPositions": [
                {
                    "coin": "BTC",
                    "position": {
                        "szi": "0.1",
                        "entryPx": "50000",
                        "leverage": {"value": 5},
                        "unrealizedPnl": "100"
                    }
                }
            ]
        }
        self.info_mock.user_state.return_value = mock_user_state

        await self.manager.update_positions()

        self.assertIn("BTC", self.manager.positions)
        pos = self.manager.positions["BTC"]
        self.assertEqual(pos.coin, "BTC")
        self.assertEqual(pos.size, 0.1)
        self.assertEqual(pos.entry_price, 50000.0)
        self.assertEqual(pos.leverage, 5)
        self.assertEqual(pos.pnl, 100.0)

    async def test_execute_copy_trade_flip_close_then_open_remaining(self):
        """If follower holds opposite position, we should close then open remainder."""
        # Arrange: follower currently short 0.5 BTC
        self.manager.positions = {
            "BTC": Position("BTC", -0.5, 50000, 3, pnl=0.0)
        }

        trade = MonitoredTrade(
            action=TradeAction.OPEN_LONG,
            coin="BTC",
            size=1.0,
            price=50000.0,
            leverage=3,
            timestamp=123,
            tx_hash="0xflip",
            side="B",
        )

        # Stub internals so we don't hit real exchange threads.
        async def _sz_decimals(_coin: str) -> int:
            return 3

        async def _close_partial(_coin: str, size: float) -> float:
            # pretend we successfully closed exactly the requested size
            return float(size)

        opened_calls = []
        async def _market_open(_coin: str, is_buy: bool, size: float):
            opened_calls.append((_coin, is_buy, float(size)))

        async def _set_leverage(_coin: str, lev: int):
            return None

        self.manager._get_sz_decimals = _sz_decimals  # type: ignore[assignment]
        self.manager._market_close_partial = _close_partial  # type: ignore[assignment]
        self.manager._market_open = _market_open  # type: ignore[assignment]
        self.manager._set_leverage = _set_leverage  # type: ignore[assignment]

        # New behavior: flip can wait for positions to update before opening.
        # Stub update_positions to simulate that the opposite position is gone after close.
        refreshed = {"n": 0}
        async def _update_positions(*_args, **_kwargs):
            refreshed["n"] += 1
            # After first refresh, assume close filled and position is flat.
            self.manager.positions = {}
            return None

        self.manager.update_positions = _update_positions  # type: ignore[assignment]

        # Act: copy_ratio=1 so desired copy_size=1.0, but we only need to close 0.5 then open 0.5.
        report = await self.manager.execute_copy_trade(
            trade,
            copy_ratio=1.0,
            max_size=100.0,
            max_leverage=5,
            max_notional_per_trade_usd=0.0,
            min_trade_size=0.01,
        )

        # Assert
        self.assertEqual(report.get("reason"), "flip")
        self.assertAlmostEqual(float(report.get("closed_size", 0.0)), 0.5, places=6)
        self.assertAlmostEqual(float(report.get("opened_size", 0.0)), 0.5, places=6)
        self.assertEqual(opened_calls, [("BTC", True, 0.5)])


if __name__ == '__main__':
    unittest.main(verbosity=2)