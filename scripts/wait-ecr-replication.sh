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

last_err=""
while [ "$SECONDS" -lt "$deadline" ]; do
  if out="$(aws ecr describe-images \
    --repository-name "$REPO" \
    --image-ids "imageTag=${TAG}" \
    --region "$DEST_REGION" \
    --query 'imageDetails[0].imageTags' \
    --output text 2>&1)"; then
    echo "✓ ${REPO}:${TAG} replicated to ${DEST_REGION} (tags: ${out})"
    exit 0
  fi
  last_err="$out"
  elapsed=$((SECONDS - (deadline - TIMEOUT)))
  echo "  … not visible yet (${elapsed}s elapsed)"
  if [[ "$last_err" == *"AccessDenied"* || "$last_err" == *"not authorized"* ]]; then
    echo "::error::ECR DescribeImages denied in ${DEST_REGION}. Add arn:aws:ecr:${DEST_REGION}:*:repository/${REPO} to the GitHub OIDC deploy role policy." >&2
    echo "$last_err" >&2
    exit 1
  fi
  sleep "$INTERVAL"
done

echo "Timed out waiting for ${REPO}:${TAG} in ${DEST_REGION}" >&2
if [ -n "$last_err" ]; then
  echo "Last error: $last_err" >&2
fi
exit 1
