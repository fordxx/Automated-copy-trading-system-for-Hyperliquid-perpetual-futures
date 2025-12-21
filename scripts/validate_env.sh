#!/bin/bash
# Environment Variables Validation Script for Hyperliquid Copy Trader
# This script validates that all required environment variables are set

echo "🔍 Validating Hyperliquid Copy Trader Environment Variables"
echo "=========================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if variable is set
check_var() {
    local var_name=$1
    local var_value=${!var_name}
    local required=$2

    if [ -z "$var_value" ]; then
        if [ "$required" = "true" ]; then
            echo -e "${RED}❌ $var_name: NOT SET (REQUIRED)${NC}"
            return 1
        else
            echo -e "${YELLOW}⚠️  $var_name: NOT SET (OPTIONAL)${NC}"
            return 0
        fi
    else
        if [ "$required" = "true" ]; then
            echo -e "${GREEN}✅ $var_name: SET${NC}"
        else
            echo -e "${GREEN}✅ $var_name: SET${NC}"
        fi
        return 0
    fi
}

# Function to validate address format
validate_address() {
    local var_name=$1
    local var_value=${!var_name}

    if [ -n "$var_value" ]; then
        if [[ $var_value =~ ^0x[a-fA-F0-9]{40}$ ]]; then
            echo -e "${GREEN}   └─ Format: VALID${NC}"
        else
            echo -e "${RED}   └─ Format: INVALID (must be 42-char hex starting with 0x)${NC}"
            return 1
        fi
    fi
    return 0
}

# Function to validate private key format
validate_private_key() {
    local var_name=$1
    local var_value=${!var_name}

    if [ -n "$var_value" ]; then
        if [[ $var_value =~ ^0x[a-fA-F0-9]{64}$ ]]; then
            echo -e "${GREEN}   └─ Format: VALID${NC}"
        else
            echo -e "${RED}   └─ Format: INVALID (must be 66-char hex starting with 0x)${NC}"
            return 1
        fi
    fi
    return 0
}

echo ""
echo "📋 REQUIRED VARIABLES:"
echo "----------------------"

# Required variables
check_var "TARGET_ADDRESS" "true"
validate_address "TARGET_ADDRESS"

check_var "HYPERLIQUID_ACCOUNT_ADDRESS" "true"
validate_address "HYPERLIQUID_ACCOUNT_ADDRESS"

check_var "HYPERLIQUID_PRIVATE_KEY" "true"
validate_private_key "HYPERLIQUID_PRIVATE_KEY"

echo ""
echo "🔧 OPTIONAL VARIABLES:"
echo "----------------------"

# Optional variables
check_var "EXCLUDE_ADDRESSES" "false"
if [ -n "$EXCLUDE_ADDRESSES" ]; then
    IFS=',' read -ra ADDR_ARRAY <<< "$EXCLUDE_ADDRESSES"
    echo "   └─ Count: ${#ADDR_ARRAY[@]} addresses"
    for addr in "${ADDR_ARRAY[@]}"; do
        addr=$(echo "$addr" | xargs)  # trim whitespace
        if [[ $addr =~ ^0x[a-fA-F0-9]{40}$ ]]; then
            echo -e "      ${GREEN}└─ $addr: VALID${NC}"
        else
            echo -e "      ${RED}└─ $addr: INVALID${NC}"
        fi
    done
fi

check_var "HYPERLIQUID_VAULT_ADDRESS" "false"
validate_address "HYPERLIQUID_VAULT_ADDRESS"

check_var "HYPERLIQUID_ENV" "false"
if [ -n "$HYPERLIQUID_ENV" ]; then
    if [[ "$HYPERLIQUID_ENV" =~ ^(mainnet|testnet)$ ]]; then
        echo -e "${GREEN}   └─ Value: $HYPERLIQUID_ENV${NC}"
    else
        echo -e "${RED}   └─ Value: $HYPERLIQUID_ENV (must be 'mainnet' or 'testnet')${NC}"
    fi
fi

check_var "TELEGRAM_ENABLED" "false"
check_var "TELEGRAM_BOT_TOKEN" "false"
check_var "TELEGRAM_CHAT_ID" "false"

check_var "COPY_RATIO" "false"
check_var "MAX_POSITION_SIZE" "false"
check_var "MIN_TRADE_SIZE" "false"
check_var "MAX_LEVERAGE" "false"

check_var "LOG_LEVEL" "false"

echo ""
echo "📊 CONFIGURATION SUMMARY:"
echo "-------------------------"

# Count set variables
REQUIRED_VARS=("TARGET_ADDRESS" "HYPERLIQUID_ACCOUNT_ADDRESS" "HYPERLIQUID_PRIVATE_KEY")
OPTIONAL_VARS=("EXCLUDE_ADDRESSES" "HYPERLIQUID_VAULT_ADDRESS" "HYPERLIQUID_ENV" "TELEGRAM_ENABLED" "TELEGRAM_BOT_TOKEN" "TELEGRAM_CHAT_ID" "COPY_RATIO" "MAX_POSITION_SIZE" "MIN_TRADE_SIZE" "MAX_LEVERAGE" "LOG_LEVEL")

required_set=0
optional_set=0

for var in "${REQUIRED_VARS[@]}"; do
    if [ -n "${!var}" ]; then
        ((required_set++))
    fi
done

for var in "${OPTIONAL_VARS[@]}"; do
    if [ -n "${!var}" ]; then
        ((optional_set++))
    fi
done

echo "Required variables set: $required_set/${#REQUIRED_VARS[@]}"
echo "Optional variables set: $optional_set/${#OPTIONAL_VARS[@]}"

echo ""
if [ $required_set -eq ${#REQUIRED_VARS[@]} ]; then
    echo -e "${GREEN}🎉 All required variables are configured!${NC}"
    echo ""
    echo "🚀 You can now run the copy trader with:"
    echo "   python scripts/run_copy_trader.py --env"
    echo ""
    echo "📖 Or use config file:"
    echo "   python scripts/run_copy_trader.py --config config/config.yaml"
else
    echo -e "${RED}❌ Some required variables are missing. Please check above.${NC}"
    echo ""
    echo "📝 Edit your .env file:"
    echo "   nano .env"
    echo ""
    echo "📋 Required variables:"
    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var}" ]; then
            echo "   - $var"
        fi
    done
fi

echo ""
echo "=========================================================="