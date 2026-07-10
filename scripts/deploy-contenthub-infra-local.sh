#!/usr/bin/env bash
# Apply prod infrastructure locally (us-east-1) — one-time / infra changes only.
# App images are deployed via deploy-prod.yml (CI) after infra is in place.
#
# Var files: prod.github.tfvars (non-secret) + prod.tfvars (secrets/overrides, optional).
#
# Usage:
#   ./scripts/deploy-contenthub-infra-local.sh          # plan + confirm + apply
#   ./scripts/deploy-contenthub-infra-local.sh plan-only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$REPO_ROOT/infrastructure/terraform/environments/us-east-1"
BACKEND_CONFIG="$REPO_ROOT/infrastructure/terraform/environments/backends/us-east-1-prod.hcl"
PLAN_ONLY="${1:-}"

# shellcheck source=scripts/terraform-var-files.sh
source "$REPO_ROOT/scripts/terraform-var-files.sh"
terraform_var_files_init prod

API_IMAGE="$(read_tfvar api_image)"

VAR_FILES=()
for arg in "${TF_VAR_FILE_ARGS[@]}"; do
  base="$(basename "${arg#-var-file=}")"
  VAR_FILES+=(-var-file="../variables/$base")
done

echo "🚀 Content Hub prod infra deploy (local Terraform, us-east-1)"
echo "   Var files: ${TF_GITHUB_VAR_FILE##*/}$([ -f "$TF_LOCAL_VAR_FILE" ] && echo " + ${TF_LOCAL_VAR_FILE##*/}")"
echo "   API domain: $(read_tfvar api_domain)"
echo "   Baseline image: $API_IMAGE"
echo ""

cd "$TF_DIR"

terraform init -reconfigure -backend-config="$BACKEND_CONFIG"
terraform validate

terraform plan \
  "${VAR_FILES[@]}" \
  -var="api_image=${API_IMAGE}" \
  -var="deploy_api_ecs_service=false" \
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
read -r -p "Apply prod infrastructure (us-east-1)? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled."
  rm -f tfplan
  exit 0
fi

terraform apply tfplan
rm -f tfplan

echo ""
echo "✅ Prod infrastructure applied (us-east-1)."
echo "Next:"
echo "  ./scripts/deploy-contenthub-secondary.sh plan-only   # review DR stack"
echo "  ./scripts/deploy-contenthub-secondary.sh             # apply us-east-2 DR"
echo "  ./scripts/deploy-api-service.sh prod                 # first API service (use1)"
echo "  GitHub: Deploy to Production workflow (app rollouts)"
