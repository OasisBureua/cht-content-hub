#!/bin/bash
# Check ACM certificate validation status (informational).
#
# Usage:
#   ./scripts/check-certificates-status.sh devhub
#   ./scripts/check-certificates-status.sh contenthub
#   ./scripts/check-certificates-status.sh devhub-use2
#   ./scripts/check-certificates-status.sh contenthub-use2

set -e

ENV="${1:-devhub}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VARS_DIR="$REPO_ROOT/infrastructure/terraform/environments/variables"

case "$ENV" in
    devhub)
        CERT_FILE="$VARS_DIR/.cert-arns-devhub"
        ;;
    devhub-use2)
        CERT_FILE="$VARS_DIR/.cert-arns-devhub-use2"
        ;;
    contenthub)
        CERT_FILE="$VARS_DIR/.cert-arns-contenthub"
        ;;
    contenthub-use2)
        CERT_FILE="$VARS_DIR/.cert-arns-contenthub-use2"
        ;;
    *)
        echo "❌ Unknown env: $ENV"
        echo "   Use: devhub | contenthub | devhub-use2 | contenthub-use2"
        exit 1
        ;;
esac

echo "🔍 Certificate status: $ENV"
echo ""

if [ ! -f "$CERT_FILE" ]; then
    echo "❌ No certificate file: $CERT_FILE"
    case "$ENV" in
        devhub-use2)  echo "   Run: ./scripts/request-certificate.sh devhub us-east-2" ;;
        devhub)       echo "   Run: ./scripts/request-certificate.sh devhub" ;;
        contenthub-use2) echo "   Run: ./scripts/request-certificate.sh contenthub us-east-2" ;;
        contenthub) echo "   Run: ./scripts/request-certificate.sh contenthub" ;;
    esac
    exit 1
fi

# shellcheck source=/dev/null
source "$CERT_FILE"

CERT_ARN="${certificate_arn:-}"
CERT_REGION="${region:-us-east-1}"

if [ -z "$CERT_ARN" ]; then
    echo "❌ certificate_arn missing in $CERT_FILE"
    exit 1
fi

STATUS=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region "$CERT_REGION" \
    --query 'Certificate.Status' \
    --output text)

echo "📍 $CERT_REGION — ${domain:-$ENV}"
echo "   ARN:    $CERT_ARN"
echo "   Status: $STATUS"
echo ""
echo "Status meanings:"
echo "  PENDING_VALIDATION — waiting for DNS CNAME"
echo "  ISSUED             — ready for ALB HTTPS ✅"
echo "  FAILED             — fix DNS and re-request"
