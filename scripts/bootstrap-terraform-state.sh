#!/usr/bin/env bash
# bootstrap-terraform-state.sh — one-time S3 bucket for Content Hub Terraform state
#
# Usage: ./scripts/bootstrap-terraform-state.sh
#
# Bucket: cht-contenthub-terraform-state
# Keys:   devhub/terraform.tfstate (dev), contenthub/terraform.tfstate (prod)

set -euo pipefail

BUCKET="cht-contenthub-terraform-state"
REGION="us-east-1"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "✓ Bucket s3://${BUCKET} already exists"
else
  echo "→ Creating s3://${BUCKET}..."
  aws s3 mb "s3://${BUCKET}" --region "$REGION"
fi

echo "→ Enabling versioning + encryption + public access block..."
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo ""
echo "✓ State bucket ready."
echo "  Dev:  s3://${BUCKET}/devhub/terraform.tfstate"
echo "  Prod: s3://${BUCKET}/contenthub/terraform.tfstate"
echo ""
echo "Next: cd infrastructure/terraform/environments/us-east-1"
echo "      terraform init -reconfigure -backend-config=../backends/us-east-1-dev.hcl"
