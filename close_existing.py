#!/usr/bin/env python3
"""关闭现有持仓"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# 读取 .env
env_vars = {}
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env_vars[key] = value

account_address = env_vars.get('HYPERLIQUID_ACCOUNT_ADDRESS')
private_key = env_vars.get('HYPERLIQUID_PRIVATE_KEY')
use_testnet = env_vars.get('HYPERLIQUID_ENV', 'mainnet').lower() == 'testnet'

base_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL

wallet = eth_account.Account.from_key(private_key)
exchange = Exchange(wallet=wallet, base_url=base_url, account_address=account_address)

print("关闭 ETH 所有持仓...")
result = exchange.market_close("ETH")
print(f"结果: {result}")
