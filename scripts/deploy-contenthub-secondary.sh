#!/usr/bin/env bash
# Deploy Content Hub DR standby (us-east-2) — shares CHT platform DR VPC.
# Var files: prod.github.tfvars (non-secret) + prod.tfvars (secrets/overrides, optional).
#
# Prerequisites:
#   1. us-east-1 prod applied (Aurora Global primary + ECR replication)
#   2. prod.github.tfvars dr_* section filled
#
# Usage:
#   ./scripts/deploy-contenthub-secondary.sh              # plan + confirm + apply
#   ./scripts/deploy-contenthub-secondary.sh plan-only
#   IMAGE_TAG=1.0.3 ./scripts/deploy-contenthub-secondary.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$REPO_ROOT/infrastructure/terraform/environments/us-east-2"
BACKEND_CONFIG="$REPO_ROOT/infrastructure/terraform/environments/backends/us-east-2-prod.hcl"
PLAN_ONLY="${1:-}"

# shellcheck source=scripts/terraform-var-files.sh
source "$REPO_ROOT/scripts/terraform-var-files.sh"
terraform_var_files_init prod

VAR_FILES=()
for arg in "${TF_VAR_FILE_ARGS[@]}"; do
  base="$(basename "${arg#-var-file=}")"
  VAR_FILES+=(-var-file="../variables/$base")
done

TF_DR_API_IMAGE="$(read_tfvar dr_api_image || true)"
ECR_REGISTRY="${ECR_REGISTRY:-233636046512.dkr.ecr.us-east-2.amazonaws.com}"

if [ -n "${API_IMAGE:-}" ]; then
  :
elif [ -n "${IMAGE_TAG:-}" ]; then
  API_IMAGE="${ECR_REGISTRY}/contenthub-api:${IMAGE_TAG}"
elif [ -n "$TF_DR_API_IMAGE" ]; then
  API_IMAGE="$TF_DR_API_IMAGE"
else
  echo "❌ Set dr_api_image in prod.github.tfvars or pass IMAGE_TAG"
  exit 1
fi

echo "🚀 Content Hub — Deploy DR standby (us-east-2 / prod)"
echo "   Var files: ${TF_GITHUB_VAR_FILE##*/}$([ -f "$TF_LOCAL_VAR_FILE" ] && echo " + ${TF_LOCAL_VAR_FILE##*/}")"
echo "   Image: $API_IMAGE"
echo ""

cd "$TF_DIR"
terraform init -reconfigure -backend-config="$BACKEND_CONFIG"
terraform validate

terraform plan \
  "${VAR_FILES[@]}" \
  -var="dr_api_image=${API_IMAGE}" \
  -out=tfplan

echo ""
echo "Plan summary:"
terraform show -json tfplan | jq -r '
  .resource_changes[]
  | select(.change.actions != ["no-op"])
  | "\(.change.actions[0]): \(.address)"
' | head -40

if [ "$PLAN_ONLY" = "plan-only" ]; then
  echo ""
  echo "Plan only — not applying."
  exit 0
fi

echo ""
read -r -p "Deploy DR stack to us-east-2? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled."
  rm -f tfplan
  exit 0
fi

terraform apply tfplan
rm -f tfplan

echo ""
echo "✅ us-east-2 DR infrastructure applied."
terraform output -json | jq -r 'to_entries[] | "\(.key): \(.value.value // .value)"' 2>/dev/null || terraform output
