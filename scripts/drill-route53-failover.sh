#!/usr/bin/env bash
# Route53 failover drill — Phase A (API traffic only, no Aurora promotion).
#
# Prerequisites:
#   1. use1 + use2 infra applied; ECS API running in BOTH regions (deploy-prod.yml / CI)
#   2. Route53 failover armed: ./scripts/arm-route53-failover.sh arm
#
# Usage:
#   ./scripts/drill-route53-failover.sh status
#   ./scripts/drill-route53-failover.sh fail-primary    # scale use1 API to 0
#   ./scripts/drill-route53-failover.sh restore-primary # scale use1 API back
#   ./scripts/drill-route53-failover.sh watch           # poll /health on api_domain
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_USE1="$REPO_ROOT/infrastructure/terraform/environments/us-east-1"
TF_USE2="$REPO_ROOT/infrastructure/terraform/environments/us-east-2"
BACKEND_USE1="$REPO_ROOT/infrastructure/terraform/environments/backends/us-east-1-prod.hcl"
BACKEND_USE2="$REPO_ROOT/infrastructure/terraform/environments/backends/us-east-2-prod.hcl"

# shellcheck source=scripts/terraform-var-files.sh
source "$REPO_ROOT/scripts/terraform-var-files.sh"
terraform_var_files_init prod

AWS_REGION_PRIMARY="${AWS_REGION_PRIMARY:-us-east-1}"
AWS_REGION_DR="${AWS_REGION_DR:-us-east-2}"
ACTION="${1:-status}"

API_DOMAIN="$(read_tfvar api_domain)"
PRIMARY_CLUSTER="$(read_tfvar project)-cluster"
DR_CLUSTER="contenthub-dr-use2-cluster"
PRIMARY_SERVICE="contenthub-api"
DR_SERVICE="contenthub-dr-use2-api"

tf_output() {
  local dir="$1" backend="$2" name="$3"
  (cd "$dir" && terraform init -reconfigure -backend-config="$backend" >/dev/null 2>&1)
  (cd "$dir" && terraform output -raw "$name" 2>/dev/null) || true
}

health_url() {
  echo "https://${API_DOMAIN}/health"
}

curl_health() {
  curl -sf --max-time 10 "$(health_url)" | head -c 200
  echo
}

ecs_scale() {
  local region="$1" cluster="$2" service="$3" count="$4"
  echo "Scaling ${service} in ${region} to desired=${count}..."
  aws ecs update-service \
    --region "$region" \
    --cluster "$cluster" \
    --service "$service" \
    --desired-count "$count" \
    --output text >/dev/null
  aws ecs wait services-stable \
    --region "$region" \
    --cluster "$cluster" \
    --services "$service"
}

route53_health_status() {
  local hc_id
  hc_id="$(tf_output "$TF_USE1" "$BACKEND_USE1" route53_primary_health_check_id)"
  if [ -z "$hc_id" ]; then
    echo "Route53 failover not enabled (no health check output)."
    return 0
  fi
  aws route53 get-health-check-status --health-check-id "$hc_id" \
    | jq -r '.StatusList[]? | "\(.Region): \(.Status)"' | head -10
}

print_status() {
  echo "API domain: ${API_DOMAIN}"
  echo "Primary ALB: $(tf_output "$TF_USE1" "$BACKEND_USE1" api_alb_dns_name)"
  echo "DR ALB:      $(tf_output "$TF_USE2" "$BACKEND_USE2" api_alb_dns_name)"
  echo "Failover:    $(tf_output "$TF_USE1" "$BACKEND_USE1" route53_failover_enabled)"
  echo ""
  echo "GET $(health_url)"
  curl_health || echo "(health check failed)"
  echo ""
  echo "Route53 primary health check:"
  route53_health_status
  echo ""
  echo "ECS desired counts:"
  aws ecs describe-services --region "$AWS_REGION_PRIMARY" \
    --cluster "$PRIMARY_CLUSTER" --services "$PRIMARY_SERVICE" \
    --query 'services[0].{desired:desiredCount,running:runningCount}' --output table 2>/dev/null \
    || echo "  Primary service not found"
  aws ecs describe-services --region "$AWS_REGION_DR" \
    --cluster "$DR_CLUSTER" --services "$DR_SERVICE" \
    --query 'services[0].{desired:desiredCount,running:runningCount}' --output table 2>/dev/null \
    || echo "  DR service not found"
}

case "$ACTION" in
  status)
    print_status
    ;;
  fail-primary)
    echo "Simulating primary API failure (scale use1 to 0)."
    echo "Expect Route53 to fail over in ~1–3 minutes after health check failures."
    ecs_scale "$AWS_REGION_PRIMARY" "$PRIMARY_CLUSTER" "$PRIMARY_SERVICE" 0
    echo "Done. Run: $0 watch"
    ;;
  restore-primary)
    DESIRED="$(read_tfvar api_desired_count || echo 2)"
    echo "Restoring primary API (desired=${DESIRED})..."
    ecs_scale "$AWS_REGION_PRIMARY" "$PRIMARY_CLUSTER" "$PRIMARY_SERVICE" "$DESIRED"
    echo "Done. DNS returns to primary when Route53 health check passes."
    ;;
  watch)
    echo "Polling $(health_url) every 15s (Ctrl+C to stop)..."
    while true; do
      date -u +"%H:%M:%S UTC"
      curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 10 "$(health_url)" || echo "HTTP failed"
      route53_health_status | head -3
      echo "---"
      sleep 15
    done
    ;;
  *)
    echo "Usage: $0 {status|fail-primary|restore-primary|watch}"
    exit 1
    ;;
esac
