#!/usr/bin/env bash
# 測試 Polymarket API 可否從目前環境連線
# 用法：bash scripts/test-poly-api.sh
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

check_endpoint() {
    local name="$1" url="$2" expected="${3:-200}"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$url" 2>/dev/null || echo "FAIL")
    if [ "$code" = "$expected" ]; then
        echo -e "${GREEN}✅ $name${NC} — HTTP $code"
    else
        echo -e "${RED}❌ $name${NC} — HTTP $code（預期 $expected）"
    fi
}

echo "=== Polymarket API 連線測試 ==="
echo ""

check_endpoint "CLOB API" "https://clob.polymarket.com/" 404
check_endpoint "Gamma API" "https://gamma-api.polymarket.com/markets?limit=1" 200
check_endpoint "Polygon RPC" "$(curl -s -X POST -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' https://polygon-rpc.com -w '%{http_code}' -o /dev/null)" 200

echo ""
echo "如果上排出現 ❌，表示 Polymarket API 在台灣被封鎖"
echo "解法：使用國外 VPS 執行此腳本，或掛 VPN 後重試"
