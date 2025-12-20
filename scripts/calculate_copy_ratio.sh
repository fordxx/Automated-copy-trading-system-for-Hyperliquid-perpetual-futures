#!/bin/bash

# 跟单比例计算器
# 帮助用户理解跟单比例的实际效果

echo "🧮 Hyperliquid Copy Trader - 跟单比例计算器"
echo "=========================================="
echo ""

# 检查是否提供了参数
if [ $# -eq 0 ]; then
    echo "用法:"
    echo "  $0 <目标交易大小> [跟单比例] [最大仓位限制]"
    echo ""
    echo "示例:"
    echo "  $0 1.0        # 计算目标交易1.0时的默认配置"
    echo "  $0 1.0 0.1    # 指定跟单比例0.1 (10%)"
    echo "  $0 1.0 0.1 0.5 # 指定跟单比例和最大仓位限制"
    echo ""
    echo "当前配置 (从config/config.yaml读取):"
    if [ -f "config/config.yaml" ]; then
        copy_ratio=$(grep "copy_ratio:" config/config.yaml | head -1 | awk '{print $2}')
        max_size=$(grep "max_position_size:" config/config.yaml | head -1 | awk '{print $2}')

        echo "  跟单比例: ${copy_ratio:-0.1} ($(echo "scale=1; ${copy_ratio:-0.1} * 100" | bc -l)%)"
        echo "  最大仓位: ${max_size:-1.0} 合约"
    else
        echo "  配置文件不存在，使用默认值"
        echo "  跟单比例: 0.1 (10%)"
        echo "  最大仓位: 1.0 合约"
    fi
    exit 0
fi

# 参数
target_size=$1
copy_ratio=${2:-0.1}
max_position=${3:-1.0}

echo "📊 计算参数:"
echo "  目标交易大小: $target_size 合约"
echo "  跟单比例: $copy_ratio (代表 $(echo "scale=1; $copy_ratio * 100" | bc -l)%)"
echo "  最大仓位限制: $max_position 合约"
echo ""

# 使用bc进行浮点计算
copy_size=$(echo "scale=6; $target_size * $copy_ratio" | bc -l)

# 判断实际大小
if (( $(echo "$copy_size > $max_position" | bc -l) )); then
    actual_size=$max_position
    limited=" (受最大仓位限制)"
else
    actual_size=$copy_size
    limited=""
fi

echo "🧮 计算结果:"
echo "  原始跟单大小 = $target_size × $copy_ratio = $copy_size 合约"
echo "  实际跟单大小 = $actual_size 合约$limited"
echo ""

# 判断是否受限
if (( $(echo "$copy_size > $max_position" | bc -l) )); then
    echo "⚠️  注意: 跟单大小受最大仓位限制"
    echo "   如需更大的仓位，请调整 max_position_size 配置"
fi

# 最小交易检查
min_trade=0.01
if (( $(echo "$actual_size < $min_trade" | bc -l) )); then
    echo "⚠️  警告: 跟单大小 ($actual_size) 小于最小交易要求 ($min_trade)"
    echo "   此交易将被跳过"
fi

echo ""
echo "💡 提示:"
echo "  - 建议从 copy_ratio = 0.001 (0.1%) 开始测试"
echo "  - 逐渐增加比例，了解系统稳定性和资金使用情况"
echo "  - 详细说明请查看 COPY_RATIO_GUIDE.md"