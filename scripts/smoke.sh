#!/usr/bin/env bash
# smoke.sh — post-deploy smoke tests (requires contenthub-api running)
#
# Usage:
#   ./scripts/smoke.sh https://devhub.communityhealth.media
#
# Note: blocked until backend is implemented and deployed.

set -u

BASE="${1:-}"
if [ -z "$BASE" ]; then
  echo "No API deployed yet — smoke tests require contenthub-api."
  echo "Usage: $0 https://devhub.communityhealth.media"
  exit 0
fi

BASE="${BASE%/}"
if [[ "$BASE" != http://* && "$BASE" != https://* ]]; then
  BASE="https://${BASE}"
fi

fail=0
for ep in /health /api/public/status; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE$ep")
  if [ "$code" != "200" ]; then
    echo "✗ $ep returned $code"
    fail=1
  else
    echo "✓ $ep 200"
  fi
done

[ "$fail" -eq 0 ] && echo "✓ smoke passed." || exit 1
