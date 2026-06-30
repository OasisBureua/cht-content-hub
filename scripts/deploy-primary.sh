#!/usr/bin/env bash
# deploy-primary.sh — Terraform plan + confirm + apply for contenthub producer stack
#
# Usage:
#   ./scripts/deploy-primary.sh dev          # plan, then yes/no to apply
#   ./scripts/deploy-primary.sh dev plan     # plan only (no apply)
#
# Dev apply is blocked until acm_certificate_arn is set (cert ISSUED).

set -euo pipefail

ENV="${1:-dev}"
PLAN_ONLY="${2:-}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infrastructure/terraform/environments/us-east-1"
VAR_FILE="$ROOT/infrastructure/terraform/environments/variables/${ENV}.tfvars"

read_tfvar() {
  grep -E "^${1}[[:space:]]*=" "$VAR_FILE" | head -1 | sed -E 's/^[^"]*"([^"]*)".*/\1/'
}

case "$ENV" in
  dev|prod) ;;
  *)
    echo "✗ Unknown environment: $ENV"
    echo "Usage: ./scripts/deploy-primary.sh [dev|prod] [plan]"
    exit 1
    ;;
esac

if [ -n "$PLAN_ONLY" ] && [ "$PLAN_ONLY" != "plan" ]; then
  echo "✗ Unknown option: $PLAN_ONLY"
  echo "Usage: ./scripts/deploy-primary.sh [dev|prod] [plan]"
  exit 1
fi

BACKEND_CONFIG="$ROOT/infrastructure/terraform/environments/backends/us-east-1-${ENV}.hcl"

if [ ! -f "$BACKEND_CONFIG" ] || [ ! -f "$VAR_FILE" ]; then
  echo "✗ Missing backend config or $VAR_FILE"
  exit 1
fi

API_DOMAIN="$(read_tfvar api_domain || true)"

STATE_KEY="$(grep -E '^key' "$BACKEND_CONFIG" | sed 's/key = "//;s/"//')"
echo "🚀 Content Hub — Deploy Primary Region (us-east-1)"
echo "=================================================="
echo ""
echo "→ Environment: $ENV"
echo "→ State:       s3://cht-contenthub-terraform-state/${STATE_KEY}"
if [ -n "$API_DOMAIN" ]; then
  echo "→ API domain:  $API_DOMAIN"
fi
if [ "$PLAN_ONLY" = "plan" ]; then
  echo "→ Mode:        plan only"
else
  echo "→ Mode:        plan + apply (confirm at prompt)"
fi
echo ""

cd "$TF_DIR"

echo "🔧 Initializing Terraform..."
terraform init -reconfigure -backend-config="$BACKEND_CONFIG"

echo ""
echo "✅ Validating configuration..."
terraform validate

if [ "$ENV" = "dev" ]; then
  CERT_ARN="$(read_tfvar acm_certificate_arn)"
  if [ -z "$CERT_ARN" ] && [ "$PLAN_ONLY" != "plan" ]; then
    echo "✗ Refusing deploy: set acm_certificate_arn in dev.tfvars after devhub cert is ISSUED."
    echo "  ./scripts/verify-certificate.sh devhub"
    exit 1
  fi
fi

echo ""
echo "📋 Planning deployment..."
terraform plan -var-file="$VAR_FILE" -out=tfplan

if command -v jq >/dev/null 2>&1; then
  echo ""
  echo "📊 Plan Summary:"
  terraform show -json tfplan | jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | "\(.change.actions[0]): \(.type).\(.name)"'
fi

if [ "$PLAN_ONLY" = "plan" ]; then
  echo ""
  echo "→ Plan saved to tfplan (not applied). Run: ./scripts/deploy-primary.sh $ENV"
  exit 0
fi

echo ""
read -r -p "Deploy to us-east-1 ($ENV)? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "❌ Deployment cancelled."
  rm -f tfplan
  exit 0
fi

echo ""
echo "🚀 Deploying infrastructure..."
terraform apply tfplan
rm -f tfplan

echo ""
echo "✅ us-east-1 ($ENV) deployed successfully!"
echo ""
echo "📋 Deployment Outputs:"
terraform output

OUTPUT_FILE="$HOME/contenthub-us-east-1-${ENV}-outputs.txt"
echo ""
echo "💾 Saving outputs to ${OUTPUT_FILE}..."
terraform output > "$OUTPUT_FILE"

echo ""
echo "📋 Next steps:"
echo "1. Add Route53 NS records to GoDaddy (if not already delegated)"
terraform output -raw next_steps
echo ""
echo "2. Point CHT dev at the producer when ready:"
echo "   MEDIAHUB_BASE_URL=https://${API_DOMAIN}/api/public"
echo "   MEDIAHUB_API_KEY=<must match content-hub public_api_key>"
echo ""
if [ -n "$API_DOMAIN" ]; then
  echo "3. Smoke test: ./scripts/smoke.sh https://${API_DOMAIN}"
else
  echo "3. Smoke test: ./scripts/smoke.sh https://devhub.communityhealth.media"
fi
