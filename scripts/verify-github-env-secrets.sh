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

optional() {
  local env_name="$1"
  local gh_name="$2"
  if [ -z "${!env_name:-}" ]; then
    echo "::warning::Optional GitHub secret $gh_name is empty (platform sync / AI may be disabled until set)."
  fi
}

missing=0
require AWS_ROLE_ARN AWS_ROLE_ARN || missing=1
require PUBLIC_API_KEY PUBLIC_API_KEY || missing=1
require WEBHOOK_API_KEY WEBHOOK_API_KEY || missing=1
require JWT_SECRET JWT_SECRET || missing=1
require INTERNAL_CACHE_SECRET INTERNAL_CACHE_SECRET || missing=1

optional OPENAI_API_KEY OPENAI_API_KEY
optional ANTHROPIC_API_KEY ANTHROPIC_API_KEY
optional LINKEDIN_CLIENT_ID LINKEDIN_CLIENT_ID
optional LINKEDIN_CLIENT_SECRET LINKEDIN_CLIENT_SECRET
optional LINKEDIN_REDIRECT_URI LINKEDIN_REDIRECT_URI
optional LINKEDIN_SCOPES LINKEDIN_SCOPES
optional LINKEDIN_ORG_URN LINKEDIN_ORG_URN
optional LINKEDIN_AD_ACCOUNT_ID LINKEDIN_AD_ACCOUNT_ID
optional LINKEDIN_ADS_CLIENT_ID LINKEDIN_ADS_CLIENT_ID
optional LINKEDIN_ADS_CLIENT_SECRET LINKEDIN_ADS_CLIENT_SECRET
optional LINKEDIN_ADS_REDIRECT_URI LINKEDIN_ADS_REDIRECT_URI
optional LINKEDIN_ADS_SCOPES LINKEDIN_ADS_SCOPES
optional YOUTUBE_API_KEY YOUTUBE_API_KEY
optional YOUTUBE_CHANNEL_ID YOUTUBE_CHANNEL_ID
optional YOUTUBE_CHANNEL_HANDLE YOUTUBE_CHANNEL_HANDLE
optional X_BEARER_TOKEN X_BEARER_TOKEN
optional X_ACCOUNT_HANDLE X_ACCOUNT_HANDLE
optional WORDPRESS_WEBHOOK_SECRET WORDPRESS_WEBHOOK_SECRET

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "Add secrets to GitHub: Settings → Environments → $ENV_LABEL → Environment secrets"
  echo "See .github/CI_CD.md for the full list and TF_VAR mapping."
  exit 1
fi

echo "✅ Required GitHub secrets are present for $ENV_LABEL"
