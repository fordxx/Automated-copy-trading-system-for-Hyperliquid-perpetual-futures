"""Tests for Hyperliquid Copy Trader."""
import unittest
from unittest.mock import Mock, patch
import asyncio

from src.trade_monitor import TradeMonitor, MonitoredTrade, TradeAction
from src.position_manager import PositionManager, Position


class TestTradeMonitor(unittest.TestCase):
    """Test cases for TradeMonitor."""

    def setUp(self):
        self.monitor = TradeMonitor("0x1234567890123456789012345678901234567890", use_testnet=True)

    @patch('src.trade_monitor.Info')
    async def test_get_recent_trades(self, mock_info_class):
        """Test getting recent trades."""
        # Mock the info client
        mock_info = Mock()
        mock_info_class.return_value = mock_info

        # Mock user fills response
        mock_fills = [
            {
                "coin": "BTC",
                "sz": "0.1",
                "px": "50000",
                "time": 1638360000000,
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


class TestPositionManager(unittest.TestCase):
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


if __name__ == '__main__':
    # Run async tests
    async def run_async_tests():
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(TestTradeMonitor)
        suite.addTests(loader.loadTestsFromTestCase(TestPositionManager))

        runner = unittest.TextTestRunner(verbosity=2)
        result = await asyncio.get_event_loop().run_until_complete(
            asyncio.gather(*[test() for test in suite])
        )
        runner.run(suite)

    asyncio.run(run_async_tests())