#!/bin/bash

# Telegram Bot Setup Guide for Hyperliquid Copy Trader

echo "📱 设置Telegram通知"
echo "===================="
echo ""

echo "步骤 1: 创建Telegram机器人"
echo "---------------------------"
echo "1. 在Telegram中搜索 @BotFather"
echo "2. 发送消息: /newbot"
echo "3. 按照提示设置机器人名称和用户名"
echo "4. 保存机器人令牌 (Bot Token)"
echo ""

echo "步骤 2: 获取你的聊天ID"
echo "----------------------"
echo "1. 在Telegram中搜索 @userinfobot"
echo "2. 发送任意消息给它"
echo "3. 它会回复你的用户信息，包含ID"
echo "4. 保存这个ID (Chat ID)"
echo ""

echo "步骤 3: 配置机器人"
echo "------------------"
echo "将以下信息添加到你的配置文件中:"
echo ""
echo "telegram:"
echo "  enabled: true"
echo "  bot_token: \"你的机器人令牌\""
echo "  chat_id: \"你的聊天ID\""
echo ""

echo "或者添加到 .env 文件中:"
echo "TELEGRAM_ENABLED=true"
echo "TELEGRAM_BOT_TOKEN=你的机器人令牌"
echo "TELEGRAM_CHAT_ID=你的聊天ID"
echo ""

echo "步骤 4: 测试配置"
echo "----------------"
echo "运行配置检查:"
echo "./scripts/check_config.sh"
echo ""

echo "步骤 5: 启动程序测试"
echo "--------------------"
echo "启动程序后，你应该会收到启动通知消息"
echo ""

echo "📋 通知类型:"
echo "- 🚀 系统启动通知"
echo "- 🟢 交易执行通知 (开仓/平仓)"
echo "- 📊 定期状态报告"
echo "- ⚠️ 风险警报 (止损/回撤)"
echo "- ❌ 错误通知"
echo "- 🛑 系统关闭通知"
echo ""

echo "🔒 安全提醒:"
echo "- 不要将机器人令牌分享给他人"
echo "- 定期检查机器人权限"
echo "- 如需停止通知，可在配置中设置 enabled: false"