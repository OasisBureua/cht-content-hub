#!/usr/bin/env bash
# Set deploy_api / deploy_sync / deploy_infra for GitHub Actions.
#
# Lanes are independent and only turn on when that tree actually changed:
#   - api   → backend/** (API image + ECS image roll)
#   - sync  → sync/** (shared Lambda zip)
#   - infra → infrastructure/** (Terraform plan/apply)
#
# force_all=true is the escape hatch (manual "deploy all", or when the change
# base SHA cannot be resolved). workflow_dispatch does NOT imply force_all.
#
# Usage: ci-detect-deploy-scope.sh <force_all> <api_changed> <sync_changed> <infra_changed>
set -euo pipefail

FORCE_ALL="${1:-false}"
API_CHANGED="${2:-false}"
SYNC_CHANGED="${3:-false}"
INFRA_CHANGED="${4:-false}"

DEPLOY_API=false
DEPLOY_SYNC=false
DEPLOY_INFRA=false

if [ "$FORCE_ALL" = "true" ]; then
  DEPLOY_API=true
  DEPLOY_SYNC=true
  DEPLOY_INFRA=true
else
  if [ "$API_CHANGED" = "true" ]; then
    DEPLOY_API=true
  fi
  if [ "$SYNC_CHANGED" = "true" ]; then
    DEPLOY_SYNC=true
  fi
  if [ "$INFRA_CHANGED" = "true" ]; then
    DEPLOY_INFRA=true
  fi
fi

{
  echo "deploy_api=$DEPLOY_API"
  echo "deploy_sync=$DEPLOY_SYNC"
  echo "deploy_infra=$DEPLOY_INFRA"
} >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT not set}"

echo "Deploy scope: api=$DEPLOY_API sync=$DEPLOY_SYNC infra=$DEPLOY_INFRA (force_all=$FORCE_ALL)"
