#!/usr/bin/env bash
# Verify required GitHub Environment secrets for deploy workflows.
#
# Modes:
#   1. CI / local with exports — checks AWS_ROLE_ARN, PUBLIC_API_KEY, … in the shell
#   2. Local without exports — uses `gh secret list --env <name>` when gh is available
#
# Usage:
#   ./scripts/verify-github-env-secrets.sh production
#   ./scripts/verify-github-env-secrets.sh development
#
# Local parity with CI (optional):
#   export AWS_ROLE_ARN=... PUBLIC_API_KEY=... WEBHOOK_API_KEY=... JWT_SECRET=... INTERNAL_CACHE_SECRET=...
#   ./scripts/verify-github-env-secrets.sh production
set -euo pipefail

ENV_LABEL="${1:-development}"
echo "Verifying GitHub secrets for: $ENV_LABEL"

REQUIRED_SECRETS=(
  AWS_ROLE_ARN
  PUBLIC_API_KEY
  WEBHOOK_API_KEY
  JWT_SECRET
  INTERNAL_CACHE_SECRET
)

OPTIONAL_SECRETS=(
  OPENAI_API_KEY
  ANTHROPIC_API_KEY
  LINKEDIN_CLIENT_ID
  LINKEDIN_CLIENT_SECRET
  LINKEDIN_REDIRECT_URI
  LINKEDIN_SCOPES
  LINKEDIN_ORG_URN
  LINKEDIN_AD_ACCOUNT_ID
  LINKEDIN_ADS_CLIENT_ID
  LINKEDIN_ADS_CLIENT_SECRET
  LINKEDIN_ADS_REDIRECT_URI
  LINKEDIN_ADS_SCOPES
  LINKEDIN_ADS_ACCESS_TOKEN
  YOUTUBE_API_KEY
  YOUTUBE_CHANNEL_ID
  YOUTUBE_CHANNEL_HANDLE
  X_BEARER_TOKEN
  X_ACCOUNT_HANDLE
  WORDPRESS_WEBHOOK_SECRET
)

env_var_set() {
  [ -n "${!1:-}" ]
}

any_required_env_set() {
  local name
  for name in "${REQUIRED_SECRETS[@]}"; do
    if env_var_set "$name"; then
      return 0
    fi
  done
  return 1
}

verify_from_shell_env() {
  local missing=0
  local name

  echo "Mode: shell environment variables"

  for name in "${REQUIRED_SECRETS[@]}"; do
    if env_var_set "$name"; then
      echo "  ✓ $name"
    else
      echo "::error::Missing environment variable $name (maps to GitHub secret $name in Environment '$ENV_LABEL')."
      missing=1
    fi
  done

  for name in "${OPTIONAL_SECRETS[@]}"; do
    if ! env_var_set "$name"; then
      echo "::warning::Optional $name is empty (platform sync / AI may be disabled until set)."
    fi
  done

  return "$missing"
}

verify_from_gh() {
  local missing=0
  local name
  local listed
  local repo

  if ! command -v gh >/dev/null 2>&1; then
    echo "::error::gh CLI not found. Install gh or export required secrets as env vars and re-run."
    return 1
  fi

  repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
  if [ -z "$repo" ]; then
    echo "::error::Could not resolve GitHub repo (run from repo root; gh auth login)."
    return 1
  fi

  echo "Mode: GitHub API (gh secret list --env $ENV_LABEL) — repo $repo"
  echo "(gh lists secret names only; values are not readable.)"
  echo ""

  listed="$(gh secret list --env "$ENV_LABEL" --json name -q '.[].name' 2>/dev/null || true)"
  if [ -z "$listed" ]; then
    echo "::error::No secrets returned for Environment '$ENV_LABEL'. Create it under Settings → Environments → $ENV_LABEL → Environment secrets."
    return 1
  fi

  secret_exists() {
    grep -qx "$1" <<< "$listed"
  }

  for name in "${REQUIRED_SECRETS[@]}"; do
    if secret_exists "$name"; then
      echo "  ✓ $name"
    else
      echo "::error::Missing GitHub secret $name in Environment '$ENV_LABEL'."
      missing=1
    fi
  done

  for name in "${OPTIONAL_SECRETS[@]}"; do
    if ! secret_exists "$name"; then
      echo "::warning::Optional GitHub secret $name is not set in Environment '$ENV_LABEL'."
    fi
  done

  return "$missing"
}

missing=0
if any_required_env_set; then
  verify_from_shell_env || missing=1
else
  verify_from_gh || missing=1
fi

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "Add secrets: Settings → Environments → $ENV_LABEL → Environment secrets"
  echo "Or verify remotely: gh secret list --env $ENV_LABEL"
  echo "See .github/CI_CD.md for the full list and TF_VAR mapping."
  exit 1
fi

echo ""
echo "✅ Required GitHub secrets are present for $ENV_LABEL"
