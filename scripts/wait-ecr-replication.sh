#!/usr/bin/env bash
# Wait until an ECR image tag is visible in the destination region (cross-region replication).
#
# Usage: ./scripts/wait-ecr-replication.sh <repository> <tag> [dest_region] [timeout_seconds]
set -euo pipefail

REPO="${1:?repository name required}"
TAG="${2:?image tag required}"
DEST_REGION="${3:-us-east-2}"
TIMEOUT="${4:-600}"
INTERVAL=15

deadline=$((SECONDS + TIMEOUT))
echo "Waiting for ${REPO}:${TAG} in ${DEST_REGION} (timeout ${TIMEOUT}s)..."

while [ "$SECONDS" -lt "$deadline" ]; do
  if aws ecr describe-images \
    --repository-name "$REPO" \
    --image-ids "imageTag=${TAG}" \
    --region "$DEST_REGION" \
    --query 'imageDetails[0].imageTags' \
    --output text >/dev/null 2>&1; then
    echo "✓ ${REPO}:${TAG} replicated to ${DEST_REGION}"
    exit 0
  fi
  sleep "$INTERVAL"
done

echo "Timed out waiting for ${REPO}:${TAG} in ${DEST_REGION}" >&2
exit 1
