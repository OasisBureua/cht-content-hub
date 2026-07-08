#!/usr/bin/env bash
# Build contenthub-api and contenthub-worker Docker images locally.
#
# Usage:
#   ./scripts/build-images.sh [VERSION]
#   ./scripts/build-images.sh dev-latest
#   ./scripts/build-images.sh $(git rev-parse --short HEAD)
set -euo pipefail

VERSION="${1:-dev-latest}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔨 Building Content Hub Docker images (tag: $VERSION)"
echo ""

echo "📦 Building contenthub-api..."
docker build -t "contenthub-api:${VERSION}" -f "$REPO_ROOT/backend/Dockerfile" "$REPO_ROOT/backend"
echo "✅ contenthub-api:${VERSION}"
echo ""

echo "📦 Building contenthub-worker (placeholder)..."
docker build -t "contenthub-worker:${VERSION}" -f "$REPO_ROOT/worker/Dockerfile" "$REPO_ROOT/worker"
echo "✅ contenthub-worker:${VERSION}"
echo ""

echo "✅ All images built."
echo ""
echo "  contenthub-api:${VERSION}"
echo "  contenthub-worker:${VERSION}"
echo ""
echo "Next: ./scripts/push-images.sh ${VERSION} us-east-1 dev"
