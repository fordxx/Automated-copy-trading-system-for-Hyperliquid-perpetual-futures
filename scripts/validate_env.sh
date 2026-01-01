#!/bin/bash
# Environment Variables Validation Script for Hyperliquid Copy Trader
# - Single-instance mode: validates TARGET_ADDRESS/HYPERLIQUID_* envs
# - Multi-instance mode: validates per-instance private keys via
#   HYPERLIQUID_PRIVATE_KEY_<INSTANCE_NAME> (recommended)

set -euo pipefail

echo "🔍 Validating Hyperliquid Copy Trader Environment Variables"
echo "=========================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

if [[ -n "${NO_COLOR:-}" || ! -t 1 ]]; then
    RED=""
    GREEN=""
    YELLOW=""
    NC=""
fi

MODE="single"
MULTI_CONFIG_PATH="config/my_multi.yaml"

usage() {
    echo "Usage: $0 [--multi --config path/to/my_multi.yaml]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --multi)
            MODE="multi"
            shift
            ;;
        --config)
            MULTI_CONFIG_PATH="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 2
            ;;
    esac
done

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

if [[ "$MODE" == "multi" ]]; then
    if [[ ! -f "$MULTI_CONFIG_PATH" ]]; then
        echo -e "${RED}❌ Multi config not found: $MULTI_CONFIG_PATH${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ Mode: multi${NC}"
    echo "Config: $MULTI_CONFIG_PATH"
    echo ""
    echo "🔐 Per-instance private keys (recommended):"
    echo "  HYPERLIQUID_PRIVATE_KEY_<INSTANCE_NAME>"
    echo "  (INSTANCE_NAME = uppercased, non-alnum -> _)"
    echo ""

    # Use Python (available in venv) to parse YAML and list enabled instances + expected env keys.
    # Output lines: instance_name<TAB>env_key<TAB>account_address
    if [[ -x ".venv/bin/python" ]]; then
        mapfile -t INST_LINES < <(.venv/bin/python - <<PY
import re, sys, yaml
from pathlib import Path

p = Path("${MULTI_CONFIG_PATH}")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
instances = cfg.get("trading_instances", []) or []

def suffix(name: str) -> str:
    raw = str(name or "").strip().upper()
    raw = re.sub(r"[^A-Z0-9]+", "_", raw).strip("_")
    return raw or "INSTANCE"

for inst in instances:
    if not inst.get("enabled", False):
        continue
    name = str(inst.get("name") or "").strip()
    acct = str(((inst.get("hyperliquid") or {}).get("account_address") or "")).strip()
    env_key = f"HYPERLIQUID_PRIVATE_KEY_{suffix(name)}"
    print(f"{name}\t{env_key}\t{acct}")
PY
        )
    else
        echo -e "${RED}❌ .venv/bin/python not found; cannot validate multi config${NC}"
        exit 1
    fi

    if [[ ${#INST_LINES[@]} -eq 0 ]]; then
        echo -e "${YELLOW}⚠️  No enabled instances found in config (nothing to validate)${NC}"
    fi

    missing=0
    invalid=0
    for line in "${INST_LINES[@]}"; do
        inst_name="$(echo "$line" | cut -f1)"
        env_key="$(echo "$line" | cut -f2)"
        acct_addr="$(echo "$line" | cut -f3)"
        echo "Instance: $inst_name"
        if [[ -n "$acct_addr" ]]; then
            # lightweight format check
            if [[ "$acct_addr" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
                echo -e "  └─ account_address: ${GREEN}VALID${NC}"
            else
                echo -e "  └─ account_address: ${RED}INVALID${NC} ($acct_addr)"
                invalid=$((invalid+1))
            fi
        fi

        val="${!env_key:-}"
        if [[ -z "$val" ]]; then
            echo -e "  └─ $env_key: ${RED}NOT SET${NC}"
            missing=$((missing+1))
        else
            echo -e "  └─ $env_key: ${GREEN}SET${NC}"
            if [[ ! "$val" =~ ^0x[a-fA-F0-9]{64}$ ]]; then
                echo -e "     └─ Format: ${RED}INVALID${NC}"
                invalid=$((invalid+1))
            else
                echo -e "     └─ Format: ${GREEN}VALID${NC}"
            fi
        fi
        echo ""
    done

    if [[ $missing -eq 0 && $invalid -eq 0 ]]; then
        echo -e "${GREEN}🎉 Multi config env validation passed.${NC}"
        echo "Run: ./scripts/manage_multi_trader.sh start --config $MULTI_CONFIG_PATH"
        exit 0
    fi

    echo -e "${RED}❌ Multi config env validation failed: missing=$missing invalid=$invalid${NC}"
    exit 1
else
    # Single-instance required variables
    check_var "TARGET_ADDRESS" "true"
    validate_address "TARGET_ADDRESS"

    check_var "HYPERLIQUID_ACCOUNT_ADDRESS" "true"
    validate_address "HYPERLIQUID_ACCOUNT_ADDRESS"

    check_var "HYPERLIQUID_PRIVATE_KEY" "true"
    validate_private_key "HYPERLIQUID_PRIVATE_KEY"
fi

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
