#!/usr/bin/env bash
# Compute the next semver ECR tag (1.0.0, then 1.0.1, 1.0.2, ...).
# Ignores rolling aliases (dev-latest, prod-latest) and non-semver tags.
#
# Usage:
#   ./scripts/next-ecr-image-tag.sh [ECR_REPO] [AWS_REGION]
#   ./scripts/next-ecr-image-tag.sh contenthub-dev-api us-east-1
#   ./scripts/next-ecr-image-tag.sh contenthub-api us-east-1
set -euo pipefail

REPO="${1:-contenthub-dev-api}"
REGION="${2:-us-east-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "::error::aws CLI required" >&2
  exit 1
fi

TAGS_FILE="$(mktemp)"
trap 'rm -f "$TAGS_FILE"' EXIT

aws ecr describe-images \
  --repository-name "$REPO" \
  --region "$REGION" \
  --query 'imageDetails[*].imageTags[]' \
  --output text 2>/dev/null \
| tr '\t' '\n' \
| grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
| sort -V \
| uniq > "$TAGS_FILE" || true

if [ ! -s "$TAGS_FILE" ]; then
  echo "1.0.0"
  exit 0
fi

LATEST="$(tail -1 "$TAGS_FILE")"
IFS=. read -r major minor patch <<< "$LATEST"
echo "${major}.${minor}.$((patch + 1))"
