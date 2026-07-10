#!/usr/bin/env bash
# Build contenthub-api Docker image locally.
#
# Usage:
#   ./scripts/build-images.sh [VERSION]
#   ./scripts/build-images.sh 1.0.0
set -euo pipefail

VERSION="${1:-dev-latest}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔨 Building contenthub-api (tag: $VERSION)"
echo ""

docker build -t "contenthub-api:${VERSION}" -f "$REPO_ROOT/backend/Dockerfile" "$REPO_ROOT/backend"
echo "✅ contenthub-api:${VERSION}"
echo ""
echo "Next: ./scripts/push-images.sh ${VERSION} us-east-1 dev"
