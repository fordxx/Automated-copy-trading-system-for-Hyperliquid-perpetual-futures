#!/bin/bash

# Hyperliquid Copy Trader Configuration Validator

echo "🔍 检查 Hyperliquid Copy Trader 配置..."

# 检查配置文件是否存在
if [ ! -f "config/config.yaml" ]; then
    echo "❌ 错误: config/config.yaml 文件不存在"
    echo "请复制 config/config.yaml 并配置你的设置"
    exit 1
fi

echo "✅ 配置文件存在"

# 检查是否设置为主网
if grep -q "use_testnet: false" config/config.yaml; then
    echo "✅ 配置为主网模式"
else
    echo "⚠️  警告: 未检测到主网配置，请检查 config/config.yaml 中的 use_testnet 设置"
fi

# 检查目标地址是否已配置
if grep -q "target_address: \"0x0000000000000000000000000000000000000000\"" config/config.yaml; then
    echo "⚠️  警告: target_address 仍为默认值，请设置要跟单的目标地址"
else
    echo "✅ target_address 已配置"
fi

# 检查排除地址配置
if grep -q "exclude_addresses:" config/config.yaml; then
    exclude_count=$(grep -c "0x" config/config.yaml | grep -v "target_address" | grep -v "account_address" | wc -l)
    if [ "$exclude_count" -gt 0 ]; then
        echo "✅ exclude_addresses 已配置 ($exclude_count 个地址)"
    else
        echo "ℹ️  exclude_addresses 配置存在但为空"
    fi
else
    echo "ℹ️  exclude_addresses 未配置 (可选)"
fi

# 检查账户地址是否已配置
if grep -q "account_address: \"\"" config/config.yaml; then
    echo "⚠️  警告: account_address 未配置，请设置你的钱包地址"
else
    echo "✅ account_address 已配置"
fi

# 检查私钥是否已配置
if grep -q "private_key: \"\"" config/config.yaml; then
    echo "⚠️  警告: private_key 未配置，请设置你的私钥"
    echo "   建议使用环境变量或 .env 文件来存储私钥"
else
    echo "✅ private_key 已配置"
fi

# 检查Telegram配置
if grep -q "enabled: true" config/config.yaml && grep -q "telegram:" config/config.yaml; then
    echo "✅ Telegram通知已启用"

    if grep -q "bot_token: \"\"" config/config.yaml; then
        echo "⚠️  警告: telegram.bot_token 未配置"
    else
        echo "✅ telegram.bot_token 已配置"
    fi

    if grep -q "chat_id: \"\"" config/config.yaml; then
        echo "⚠️  警告: telegram.chat_id 未配置"
    else
        echo "✅ telegram.chat_id 已配置"
    fi
else
    echo "ℹ️  提示: Telegram通知未启用 (可选功能)"
fi

# 检查环境变量文件
if [ -f ".env" ]; then
    echo "✅ 发现 .env 文件 (推荐的安全配置方式)"
else
    echo "ℹ️  提示: 建议创建 .env 文件来安全存储私钥"
    echo "   复制 .env.template 到 .env 并填写你的配置"
fi

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "✅ 虚拟环境存在"
else
    echo "⚠️  警告: 虚拟环境不存在，请运行 ./scripts/setup.sh"
fi

# 检查依赖
if [ -f "requirements.txt" ]; then
    echo "✅ 依赖文件存在"
else
    echo "❌ 错误: requirements.txt 文件不存在"
fi

echo ""
echo "🎯 跟单比例检查:"
grep "copy_ratio:" config/config.yaml || echo "   未找到 copy_ratio 配置"

echo ""
echo "💰 最大仓位检查:"
grep "max_position_size:" config/config.yaml || echo "   未找到 max_position_size 配置"

echo ""
echo "📋 总结:"
echo "   - 确保所有配置都已正确填写"
echo "   - copy_ratio 是跟单目标交易大小的比例 (0.001 = 0.1%)"
echo "   - 建议从小额开始测试，了解系统运行后再调整比例"
echo "   - 密切监控系统运行状态，准备好随时停止程序"