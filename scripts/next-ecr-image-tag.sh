#!/usr/bin/env bash
# Compute the next semver ECR tag for Content Hub images.
#
# Rules (each deploy bumps by one step):
#   1.0.0 → 1.0.1 → … → 1.0.9 → 1.1.0 → … → 1.1.9 → 1.2.0 → … → 1.9.9 → 2.0.0
# Patch and minor use single digits 0–9; at 9 the next segment rolls and the lower resets to 0.
#
# develop and feature/** deploys share one counter on contenthub-dev-api (same ECR repo).
# prod uses contenthub-api independently.
#
# Ignores rolling aliases (dev-latest, prod-latest) and non-semver tags.
#
# Usage:
#   ./scripts/next-ecr-image-tag.sh [ECR_REPO] [AWS_REGION]
#   ./scripts/next-ecr-image-tag.sh --bump 1.0.9    # print next tag (no AWS)
#   ./scripts/next-ecr-image-tag.sh --self-test
set -euo pipefail

bump_semver() {
  local tag="$1"
  local major minor patch
  IFS=. read -r major minor patch <<< "$tag"
  major=${major:-0}
  minor=${minor:-0}
  patch=${patch:-0}

  if [ "$patch" -ge 9 ]; then
    if [ "$minor" -ge 9 ]; then
      echo "$((major + 1)).0.0"
    else
      echo "${major}.$((minor + 1)).0"
    fi
  else
    echo "${major}.${minor}.$((patch + 1))"
  fi
}

self_test() {
  local got
  got="$(bump_semver 1.0.0)"; [ "$got" = "1.0.1" ] || { echo "fail 1.0.0 -> $got"; return 1; }
  got="$(bump_semver 1.0.8)"; [ "$got" = "1.0.9" ] || { echo "fail 1.0.8 -> $got"; return 1; }
  got="$(bump_semver 1.0.9)"; [ "$got" = "1.1.0" ] || { echo "fail 1.0.9 -> $got"; return 1; }
  got="$(bump_semver 1.1.9)"; [ "$got" = "1.2.0" ] || { echo "fail 1.1.9 -> $got"; return 1; }
  got="$(bump_semver 1.9.9)"; [ "$got" = "2.0.0" ] || { echo "fail 1.9.9 -> $got"; return 1; }
  echo "next-ecr-image-tag self-test ok"
}

if [ "${1:-}" = "--bump" ]; then
  bump_semver "${2:?tag required, e.g. 1.0.9}"
  exit 0
fi

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit 0
fi

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
bump_semver "$LATEST"
