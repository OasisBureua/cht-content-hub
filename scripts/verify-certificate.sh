#!/bin/bash
# Exit 0 only when ACM certificate status is ISSUED (for deploy gates / CI).
#
# Usage:
#   ./scripts/verify-certificate.sh devhub
#   ./scripts/verify-certificate.sh contenthub

set -e

ENV="${1:-devhub}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VARS_DIR="$REPO_ROOT/infrastructure/terraform/environments/variables"

case "$ENV" in
    devhub)          CERT_FILE="$VARS_DIR/.cert-arns-devhub" ;;
    devhub-use2)     CERT_FILE="$VARS_DIR/.cert-arns-devhub-use2" ;;
    contenthub)      CERT_FILE="$VARS_DIR/.cert-arns-contenthub" ;;
    contenthub-use2) CERT_FILE="$VARS_DIR/.cert-arns-contenthub-use2" ;;
    *)
        echo "❌ Unknown env: $ENV"
        exit 1
        ;;
esac

if [ ! -f "$CERT_FILE" ]; then
    echo "❌ No certificate file. Run ./scripts/request-certificate.sh first."
    exit 1
fi

# shellcheck source=/dev/null
source "$CERT_FILE"

CERT_ARN="${certificate_arn:-}"
CERT_REGION="${region:-us-east-1}"

STATUS=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region "$CERT_REGION" \
    --query 'Certificate.Status' \
    --output text)

if [ "$STATUS" = "ISSUED" ]; then
    echo "✅ Certificate ISSUED — ${domain:-$ENV} ($CERT_REGION)"
    exit 0
fi

echo "❌ Certificate not ready: $STATUS (${domain:-$ENV})"
echo "   Run: ./scripts/check-certificates-status.sh $ENV"
exit 1
