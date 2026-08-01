#!/usr/bin/env bash

set -euo pipefail

BASE="http://localhost:8000"

# docker-compose.yml lives in deploy/, not repo root — --project-directory .
# keeps build context/bind mounts/.env resolution and the Compose project
# name (container/volume naming) pinned to repo root, same as before the
# move, instead of drifting to deploy/ (Compose's default: the directory of
# the first -f file). Run this script from the repo root.
COMPOSE=(docker compose -f deploy/docker-compose.yml --project-directory .)

############################################
# Colors
############################################

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS:${NC} $1"; }
fail() { echo -e "${RED}FAIL:${NC} $1"; exit 1; }
info() { echo -e "${BLUE}INFO:${NC} $1"; }
warn() { echo -e "${YELLOW}WARN:${NC} $1"; }

############################################
# Dependencies
############################################

command -v jq >/dev/null 2>&1 || fail "jq is required but not installed"

############################################
# Cleanup on exit
############################################

trap '"${COMPOSE[@]}" down -v' EXIT

############################################
# Start containers
############################################

info "Starting containers..."

"${COMPOSE[@]}" down -v
"${COMPOSE[@]}" up --build -d

############################################
# Wait for DB
############################################

info "Waiting for database..."

for i in {1..20}; do
    if "${COMPOSE[@]}" exec -T db pg_isready -U postgres > /dev/null 2>&1; then
        pass "Database ready"
        break
    fi

    if [ "$i" -eq 20 ]; then
        fail "Database did not start"
    fi

    sleep 1
done

############################################
# Wait for API
############################################

info "Waiting for API..."

for i in {1..30}; do
    if curl -sf "$BASE/docs" > /dev/null; then
        pass "API ready"
        break
    fi

    if [ "$i" -eq 30 ]; then
        fail "API did not become ready"
    fi

    sleep 1
done

############################################
# Test 1 — Create Product
############################################

info "Testing POST /api/products"

SKU="test-sku-$(date +%s)"
EVENT_PURCHASE="evt-purchase-$(date +%s)"
EVENT_SALE="evt-sale-$(date +%s)"
EVENT_OVERSALE="evt-oversale-$(date +%s)"

response=$(curl -s -w "%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"test-product\",\"sku\":\"$SKU\"}")

body="${response::-3}"
status="${response: -3}"

if [[ "$status" != "201" ]]; then
    echo "Body: $body"
    fail "Create product failed"
fi

product_id=$(echo "$body" | jq -r '.id')

if [[ -z "$product_id" || "$product_id" == "null" ]]; then
    fail "Could not extract product id"
fi

pass "Product created with id $product_id"

############################################
# Test 2 — Purchase Event
############################################

info "Testing PURCHASE event"

purchase_response=$(curl -s -w "%{http_code}" -X POST "$BASE/api/inventory/events" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":$product_id,\"event_type\":\"PURCHASE\",\"quantity\":50,\"event_id\":\"$EVENT_PURCHASE\"}")

purchase_body="${purchase_response::-3}"
purchase_status="${purchase_response: -3}"

if [[ "$purchase_status" != "201" ]]; then
    echo "Body: $purchase_body"
    fail "Purchase event failed"
fi

pass "Purchase event recorded"

############################################
# Test 3 — Verify Inventory = 50
############################################

info "Testing inventory lookup"

inventory_response=$(curl -s -w "%{http_code}" -X GET "$BASE/api/inventory/$product_id")

inventory_body="${inventory_response::-3}"
inventory_status="${inventory_response: -3}"

if [[ "$inventory_status" != "200" ]]; then
    fail "Inventory lookup failed"
fi

quantity=$(echo "$inventory_body" | jq -r '.inventory')

if [[ "$quantity" != "50" ]]; then
    fail "Expected inventory 50, got $quantity"
fi

pass "Inventory correctly updated to 50"

############################################
# Test 4 — Sale Event
############################################

info "Testing SALE event"

sale_response=$(curl -s -w "%{http_code}" -X POST "$BASE/api/inventory/events" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":$product_id,\"event_type\":\"SALE\",\"quantity\":10,\"event_id\":\"$EVENT_SALE\"}")

sale_body="${sale_response::-3}"
sale_status="${sale_response: -3}"

if [[ "$sale_status" != "201" ]]; then
    echo "Body: $sale_body"
    fail "Sale event failed"
fi

pass "Sale event recorded"

############################################
# Test 5 — Verify Inventory = 40
############################################

info "Testing inventory after sale"

inventory_response=$(curl -s -w "%{http_code}" -X GET "$BASE/api/inventory/$product_id")

inventory_body="${inventory_response::-3}"
quantity=$(echo "$inventory_body" | jq -r '.inventory')

if [[ "$quantity" != "40" ]]; then
    fail "Expected inventory 40, got $quantity"
fi

pass "Inventory correctly updated to 40"

############################################
# Test 6 — Oversell Protection
############################################

info "Testing oversell protection"

oversell_response=$(curl -s -w "%{http_code}" -X POST "$BASE/api/inventory/events" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":$product_id,\"event_type\":\"SALE\",\"quantity\":100,\"event_id\":\"$EVENT_OVERSALE\"}")

oversell_body="${oversell_response::-3}"
oversell_status="${oversell_response: -3}"

if [[ "$oversell_status" != "400" ]]; then
    echo "Body: $oversell_body"
    fail "Oversell protection not triggered"
fi

pass "Oversell correctly rejected"

############################################
# Test 7 — Idempotency Check
############################################

info "Testing idempotency (same event_id)"

idem_response=$(curl -s -w "%{http_code}" -X POST "$BASE/api/inventory/events" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":$product_id,\"event_type\":\"PURCHASE\",\"quantity\":50,\"event_id\":\"$EVENT_PURCHASE\"}")

idem_status="${idem_response: -3}"

if [[ "$idem_status" != "200" && "$idem_status" != "201" ]]; then
    fail "Idempotency failed"
fi

pass "Idempotency works (duplicate ignored)"

############################################

echo ""
echo -e "${GREEN}All system tests passed successfully${NC}"