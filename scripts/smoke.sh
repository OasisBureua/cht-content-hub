#!/usr/bin/env bash
# smoke.sh — post-deploy smoke tests (requires contenthub-api running)
#
# Usage:
#   ./scripts/smoke.sh https://devhub.communityhealth.media

set -u

BASE="${1:-}"
if [ -z "$BASE" ]; then
  echo "Usage: $0 https://devhub.communityhealth.media"
  exit 1
fi

BASE="${BASE%/}"
if [[ "$BASE" != http://* && "$BASE" != https://* ]]; then
  BASE="https://${BASE}"
fi

fail=0
for ep in /health /health/ready /health/live /actuator/info; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE$ep")
  if [ "$code" != "200" ]; then
    echo "✗ $ep returned $code"
    fail=1
  else
    echo "✓ $ep 200"
  fi
done

if [ -n "${PUBLIC_API_KEY:-}" ]; then
  echo "→ public API checks (X-API-Key set)"
  kols_code=$(curl -s -o /tmp/smoke-kols.json -w "%{http_code}" --max-time 15 \
    -H "X-API-Key: $PUBLIC_API_KEY" "$BASE/api/public/kols?limit=500")
  if [ "$kols_code" != "200" ]; then
    echo "✗ GET /api/public/kols returned $kols_code"
    fail=1
  else
    total=$(python3 -c "import json; print(json.load(open('/tmp/smoke-kols.json')).get('total', '?'))" 2>/dev/null || echo "?")
    echo "✓ GET /api/public/kols 200 (total=$total)"
  fi

  upsert_code=$(curl -s -o /tmp/smoke-upsert.json -w "%{http_code}" --max-time 15 \
    -H "X-API-Key: $PUBLIC_API_KEY" -H "Content-Type: application/json" \
    -d '{"npi":"1999999992","first_name":"Smoke","last_name":"Test","source":"cht-smoke"}' \
    "$BASE/api/public/hcp/upsert")
  if [ "$upsert_code" != "200" ]; then
    echo "✗ POST /api/public/hcp/upsert returned $upsert_code"
    cat /tmp/smoke-upsert.json 2>/dev/null || true
    fail=1
  else
    echo "✓ POST /api/public/hcp/upsert 200"
  fi
else
  echo "→ skip public API checks (set PUBLIC_API_KEY to test /kols and /hcp/upsert)"
fi

[ "$fail" -eq 0 ] && echo "✓ smoke passed." || exit 1
