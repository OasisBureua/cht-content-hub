#!/usr/bin/env bash
# Arm (or disarm) Route53 PRIMARY/SECONDARY failover without editing tfvars.
#
# Infra deploy keeps enable_route53_failover=false. Run this only when:
#   1. use1 + use2 stacks applied (DR ALB exists)
#   2. ECS API is running in BOTH regions (via deploy-prod.yml / CI — not Terraform)
#
# Usage:
#   ./scripts/arm-route53-failover.sh plan          # preview
#   ./scripts/arm-route53-failover.sh arm           # apply failover DNS + health check
#   ./scripts/arm-route53-failover.sh disarm        # revert to single A record → use1
#   ./scripts/arm-route53-failover.sh status        # show current setting + health
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$REPO_ROOT/infrastructure/terraform/environments/us-east-1"
BACKEND_CONFIG="$REPO_ROOT/infrastructure/terraform/environments/backends/us-east-1-prod.hcl"
ACTION="${1:-status}"

# shellcheck source=scripts/terraform-var-files.sh
source "$REPO_ROOT/scripts/terraform-var-files.sh"
terraform_var_files_init prod

VAR_FILES=()
for arg in "${TF_VAR_FILE_ARGS[@]}"; do
  base="$(basename "${arg#-var-file=}")"
  VAR_FILES+=(-var-file="../variables/$base")
done

failover_var() {
  local enabled="$1"
  echo "-var=enable_route53_failover=${enabled}"
}

cd "$TF_DIR"
terraform init -reconfigure -backend-config="$BACKEND_CONFIG" >/dev/null

case "$ACTION" in
  status)
    ENABLED="$(terraform output -raw route53_failover_enabled 2>/dev/null || echo unknown)"
    API_DOMAIN="$(read_tfvar api_domain || true)"
    echo "route53_failover_enabled (applied): ${ENABLED}"
    echo "api_domain: ${API_DOMAIN}"
    if [ "$ENABLED" = "true" ]; then
      echo ""
      echo "Primary health check:"
      HC="$(terraform output -raw route53_primary_health_check_id 2>/dev/null || true)"
      if [ -n "$HC" ]; then
        aws route53 get-health-check-status --health-check-id "$HC" \
          | jq -r '.StatusList[]? | "\(.Region): \(.Status)"' | head -5
      fi
    else
      echo ""
      echo "Failover is not armed. To arm after ECS is up in both regions:"
      echo "  ./scripts/arm-route53-failover.sh plan"
      echo "  ./scripts/arm-route53-failover.sh arm"
    fi
    ;;
  plan)
    echo "Plan: arm Route53 failover (PRIMARY use1 / SECONDARY use2)..."
    terraform plan \
      "${VAR_FILES[@]}" \
      "$(failover_var true)" \
      -var="deploy_api_ecs_service=false"
    ;;
  arm)
    echo "Arming Route53 failover..."
    terraform apply \
      "${VAR_FILES[@]}" \
      "$(failover_var true)" \
      -var="deploy_api_ecs_service=false" \
      -auto-approve
    echo ""
    echo "✅ Failover armed. Steady state: traffic stays on use1 while healthy."
    echo "   Drill: ./scripts/drill-route53-failover.sh fail-primary"
    ;;
  disarm)
    echo "Disarming Route53 failover (single record → use1)..."
    terraform apply \
      "${VAR_FILES[@]}" \
      "$(failover_var false)" \
      -var="deploy_api_ecs_service=false" \
      -auto-approve
    echo "✅ Failover disarmed."
    ;;
  *)
    echo "Usage: $0 {status|plan|arm|disarm}"
    exit 1
    ;;
esac
