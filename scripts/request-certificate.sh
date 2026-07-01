#!/bin/bash
# Request ACM certificate for devhub or contenthub domains (Content Hub producer API ALB).
# DNS is on GoDaddy — add the CNAME record there after running this script.
#
# Usage:
#   ./scripts/request-certificate.sh devhub              # us-east-1 (primary)
#   ./scripts/request-certificate.sh devhub us-east-2    # DR standby ALB
#   ./scripts/request-certificate.sh contenthub          # us-east-1 (primary)
#   ./scripts/request-certificate.sh contenthub us-east-2  # DR standby ALB

set -e

APP="${1:-}"
REGION="${2:-us-east-1}"

usage() {
    echo "Usage: $0 <devhub|contenthub> [us-east-1|us-east-2]"
    echo ""
    echo "Examples:"
    echo "  $0 devhub              # devhub.communityhealth.media in us-east-1"
    echo "  $0 devhub us-east-2    # devhub.communityhealth.media in us-east-2"
    echo "  $0 contenthub          # contenthub.communityhealth.media in us-east-1"
    echo "  $0 contenthub us-east-2  # contenthub.communityhealth.media in us-east-2"
    exit 1
}

case "$APP" in
    devhub)
        DOMAIN="devhub.communityhealth.media"
        DNS_LABEL="devhub"
        TFVARS_FILE="dev.tfvars"
        ;;
    contenthub)
        DOMAIN="contenthub.communityhealth.media"
        DNS_LABEL="contenthub"
        TFVARS_FILE="prod.tfvars"
        ;;
    *)
        usage
        ;;
esac

case "$REGION" in
    us-east-1|us-east-2) ;;
    *)
        echo "❌ Unsupported region: $REGION"
        echo "   Use us-east-1 or us-east-2"
        exit 1
        ;;
esac

if [ "$REGION" = "us-east-2" ]; then
    CERT_FILE="infrastructure/terraform/environments/variables/.cert-arns-${APP}-use2"
    STATUS_ENV="${APP}-use2"
else
    CERT_FILE="infrastructure/terraform/environments/variables/.cert-arns-${APP}"
    STATUS_ENV="$APP"
fi

echo "🔐 Request ACM Certificate for $DOMAIN"
echo "========================================"
echo ""
echo "App:      $APP"
echo "Domain:   $DOMAIN"
echo "Region:   $REGION"
echo "Validation: DNS (add CNAME in GoDaddy)"
echo ""

# Request certificate (wildcard covers subdomains if added later)
CERT_ARN=$(aws acm request-certificate \
    --domain-name "*.${DOMAIN}" \
    --subject-alternative-names "${DOMAIN}" \
    --validation-method DNS \
    --region "$REGION" \
    --query 'CertificateArn' \
    --output text)

echo "✅ Certificate requested"
echo "   ARN: $CERT_ARN"
echo ""

# Wait for validation options to appear
sleep 5

echo "📋 DNS Validation Records (add in GoDaddy):"
echo ""

echo ""
echo "📝 Add these CNAME records in GoDaddy (dns.godaddy.com):"
echo ""

for i in 0 1; do
    RECORD_NAME=$(aws acm describe-certificate \
        --certificate-arn "$CERT_ARN" \
        --region "$REGION" \
        --query "Certificate.DomainValidationOptions[$i].ResourceRecord.Name" \
        --output text 2>/dev/null || true)
    RECORD_VALUE=$(aws acm describe-certificate \
        --certificate-arn "$CERT_ARN" \
        --region "$REGION" \
        --query "Certificate.DomainValidationOptions[$i].ResourceRecord.Value" \
        --output text 2>/dev/null || true)
    if [ -n "$RECORD_NAME" ] && [ "$RECORD_NAME" != "None" ]; then
        echo "--- Record $((i+1)) ---"
        echo "Type:  CNAME"
        echo "Name:  $RECORD_NAME"
        echo "Value: $RECORD_VALUE"
        echo "TTL:   600"
        echo ""
    fi
done

RECORD_NAME=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region "$REGION" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Name' \
    --output text)
RECORD_VALUE=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region "$REGION" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Value' \
    --output text)

# GoDaddy host field: strip trailing dot and zone suffix (e.g. communityhealth.media).
GODADDY_HOST="${RECORD_NAME%.}"
GODADDY_HOST="${GODADDY_HOST%.communityhealth.media}"

echo "Primary CNAME (add in GoDaddy):"
echo "  Name:  $RECORD_NAME"
echo "  Value: $RECORD_VALUE"
echo "  TTL:   600"
echo ""
echo "In GoDaddy (zone: communityhealth.media) → DNS → Add → Type: CNAME"
echo "  Host/Name: $GODADDY_HOST"
echo "  Points to: $RECORD_VALUE"
echo "  TTL:       600 (or default)"
echo ""
echo "  ⚠️  Use the exact Host/Name above — NOT _acme-challenge.${DNS_LABEL} (that is Let's Encrypt, not ACM)."
echo ""

mkdir -p infrastructure/terraform/environments/variables
{
    echo "certificate_arn=\"$CERT_ARN\""
    echo "region=\"$REGION\""
    echo "domain=\"$DOMAIN\""
    echo "${APP}_domain=\"$DOMAIN\""
} > "$CERT_FILE"

echo "💾 Certificate ARN saved to $CERT_FILE"
echo ""
echo "📋 Next steps:"
echo "1. Add the CNAME record in GoDaddy"
echo "2. Wait 5-30 min for validation: ./scripts/check-certificates-status.sh $STATUS_ENV"
echo "3. Confirm issued: ./scripts/verify-certificate.sh $STATUS_ENV"
if [ "$REGION" = "us-east-2" ]; then
    echo "4. Once ISSUED, set dr_acm_certificate_arn in $TFVARS_FILE"
    echo "5. Deploy standby: cd infrastructure/terraform/environments/us-east-2 && terraform apply -var-file=../variables/$TFVARS_FILE"
else
    echo "4. Once ISSUED, update $TFVARS_FILE:"
    echo "     api_domain = \"$DOMAIN\""
    echo "     acm_certificate_arn = \"$CERT_ARN\""
    echo "5. CHT CONTENTHUB_BASE_URL=https://${DOMAIN}/api/public"
    echo "6. Deploy primary: cd infrastructure/terraform/environments/us-east-1 && terraform apply -var-file=../variables/$TFVARS_FILE"
fi
