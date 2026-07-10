#!/usr/bin/env bash
# Set deploy_backend output for GitHub Actions (dorny/paths-filter).
# Content Hub is API-only — no frontend lane.
#
# Usage: ci-detect-deploy-scope.sh <event_name> <api_changed> <infra_changed>
set -euo pipefail

EVENT_NAME="${1:?event name required}"
API_CHANGED="${2:-false}"
INFRA_CHANGED="${3:-false}"

DEPLOY_BACKEND=false

if [ "$EVENT_NAME" = "workflow_dispatch" ]; then
  DEPLOY_BACKEND=true
elif [ "$API_CHANGED" = "true" ] || [ "$INFRA_CHANGED" = "true" ]; then
  DEPLOY_BACKEND=true
fi

{
  echo "deploy_backend=$DEPLOY_BACKEND"
  echo "deploy_frontend=false"
} >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT not set}"

echo "Deploy scope: backend=$DEPLOY_BACKEND frontend=false"
