#!/usr/bin/env bash
# Fail fast when required GitHub Environment secrets are missing/empty.
# Mirrors local TF_VAR_* exports used with dev.tfvars.
#
# Usage:
#   ./scripts/verify-github-env-secrets.sh development
set -euo pipefail

ENV_LABEL="${1:-development}"
echo "Verifying GitHub secrets for: $ENV_LABEL"

require() {
  local env_name="$1"
  local gh_name="$2"
  if [ -z "${!env_name:-}" ]; then
    echo "::error::Missing GitHub secret $gh_name in Environment '$ENV_LABEL'. Add it under Settings → Environments → $ENV_LABEL → Environment secrets."
    return 1
  fi
}

missing=0
require AWS_ROLE_ARN AWS_ROLE_ARN || missing=1
require PUBLIC_API_KEY PUBLIC_API_KEY || missing=1
require WEBHOOK_API_KEY WEBHOOK_API_KEY || missing=1
require JWT_SECRET JWT_SECRET || missing=1
require INTERNAL_CACHE_SECRET INTERNAL_CACHE_SECRET || missing=1

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "Add secrets to GitHub: Settings → Environments → $ENV_LABEL → Environment secrets"
  echo "See .github/CI_CD.md for the full list and TF_VAR mapping."
  exit 1
fi

echo "✅ Required GitHub secrets are present for $ENV_LABEL"
