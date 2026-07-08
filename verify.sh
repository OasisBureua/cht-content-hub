#!/usr/bin/env bash
# verify.sh — run before pushing (infra-focused until backend lands)
#
# Usage:
#   ./verify.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
fail=0

run_step() {
  local label="$1"; shift
  echo "→ $label"
  if ! "$@"; then
    echo "✗ $label FAILED"
    fail=1
  fi
}

if [ -d "$REPO_ROOT/infrastructure/terraform/environments/us-east-1" ]; then
  run_step "terraform validate" bash -c "
    cd '$REPO_ROOT/infrastructure/terraform/environments/us-east-1'
    terraform init -backend=false >/dev/null
    terraform validate
  "
fi

cd "$REPO_ROOT"
staged_envs=$(git diff --cached --name-only 2>/dev/null | grep -E '(^|/)\.env(\..*)?$' || true)
if [ -n "$staged_envs" ]; then
  echo "✗ Refusing to commit .env files:"
  echo "$staged_envs"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "✗ verify FAILED"
  exit 1
fi

echo ""
echo "✓ verify passed."
