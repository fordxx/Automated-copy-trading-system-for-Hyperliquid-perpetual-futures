#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "🔒 Applying basic local security hardening..."

# Protect secret-bearing files
if [ -f ".env" ]; then
  chmod 600 .env
  echo "✅ chmod 600 .env"
else
  echo "ℹ️  .env not found (skipping)"
fi

if [ -f "config/config.yaml" ]; then
  chmod 600 config/config.yaml
  echo "✅ chmod 600 config/config.yaml"
else
  echo "ℹ️  config/config.yaml not found (skipping)"
fi

# Avoid world-readable logs (may contain addresses/trade history)
if [ -d "logs" ]; then
  chmod 700 logs || true
  echo "✅ chmod 700 logs"
fi

echo "✅ Done."