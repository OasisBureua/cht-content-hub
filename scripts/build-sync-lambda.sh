#!/usr/bin/env bash
# build-sync-lambda.sh — package sync jobs for AWS Lambda (dev + prod use same artifact)
#
# Usage:
#   ./scripts/build-sync-lambda.sh [VERSION]
#
# Output:
#   dist/sync-lambda.zip
#   dist/sync-lambda-<VERSION>.zip  (immutable copy when VERSION set)

set -euo pipefail

VERSION="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$REPO_ROOT/dist/sync-lambda-build"
OUT_DIR="$REPO_ROOT/dist"
OUT_ZIP="$OUT_DIR/sync-lambda.zip"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 required"
  exit 1
fi

echo "→ clean build dir"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$OUT_DIR"

echo "→ install dependencies"
"$PYTHON" -m pip install -r "$REPO_ROOT/sync/requirements.txt" -t "$BUILD_DIR" --quiet --upgrade

echo "→ copy sync handlers"
cp -R "$REPO_ROOT/sync/jobs" "$REPO_ROOT/sync/shared" "$BUILD_DIR/"

echo "→ copy backend application modules"
rsync -a \
  --exclude '__pycache__' \
  --exclude 'tests' \
  --exclude '*.pyc' \
  "$REPO_ROOT/backend/src/" "$BUILD_DIR/"

echo "→ strip bulky test / cache dirs from vendored packages"
find "$BUILD_DIR" -type d \( -name '__pycache__' -o -name 'tests' -o -name 'test' \) -prune -exec rm -rf {} + 2>/dev/null || true

echo "→ zip"
rm -f "$OUT_ZIP"
(
  cd "$BUILD_DIR"
  zip -r9q "$OUT_ZIP" . -x '*.pyc' -x '*__pycache__*'
)

if [ -n "$VERSION" ]; then
  cp "$OUT_ZIP" "$OUT_DIR/sync-lambda-${VERSION}.zip"
  echo "✓ $OUT_DIR/sync-lambda-${VERSION}.zip"
fi

BYTES=$(wc -c < "$OUT_ZIP" | tr -d ' ')
echo "✓ $OUT_ZIP (${BYTES} bytes)"
if [ "$BYTES" -gt 52428800 ]; then
  echo "⚠ package exceeds 50MB — use S3 deployment (set sync_lambda_s3_bucket in tfvars)"
fi

rm -rf "$BUILD_DIR"
