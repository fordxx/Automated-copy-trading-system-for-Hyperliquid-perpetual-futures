#!/bin/bash

# Hyperliquid Copy Trader Setup Script

echo "🚀 Setting up Hyperliquid Copy Trader"

# 检查Python版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# 创建虚拟环境
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 安装依赖
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# 创建日志目录
echo "📁 Creating log directory..."
mkdir -p logs

# 检查配置文件
if [ ! -f config/config.yaml ]; then
    echo "⚠️  Config file not found. Please copy and configure config/config.yaml"
    echo "   Example configuration:"
    echo "   target_address: \"0x...\"  # Address to copy trades from"
    echo "   hyperliquid:"
    echo "     account_address: \"0x...\"  # Your wallet address"
    echo "     private_key: \"0x...\"      # Your private key"
    echo "     use_testnet: false"
    echo "   telegram:"
    echo "     enabled: true              # Enable Telegram notifications"
    echo "     bot_token: \"...\"          # Your bot token from @BotFather"
    echo "     chat_id: \"...\"            # Your chat ID from @userinfobot"
else
    echo "✅ Config file found"
fi

echo "✅ Setup complete!"
echo ""
echo "To start the copy trader:"
echo "  source venv/bin/activate"
echo "  python scripts/run_copy_trader.py"
echo ""
echo "⚠️  IMPORTANT: Start with very small copy_ratio (0.001 = 0.1%)!"
echo "   Monitor closely and adjust settings as needed."