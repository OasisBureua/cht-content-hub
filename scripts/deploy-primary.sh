#!/usr/bin/env bash
# deploy-primary.sh — Terraform apply for contenthub producer stack
#
# Usage:
#   ./scripts/deploy-primary.sh dev
#   ./scripts/deploy-primary.sh prod

set -euo pipefail

ENV="${1:-dev}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infrastructure/terraform/environments/us-east-1"
VAR_FILE="$ROOT/infrastructure/terraform/environments/variables/${ENV}.tfvars"

if [ ! -d "$TF_DIR" ]; then
  echo "✗ Terraform env not found: $TF_DIR"
  exit 1
fi

cd "$TF_DIR"
terraform init

if [ -f "$VAR_FILE" ]; then
  terraform plan -var-file="$VAR_FILE" -out=tfplan
  terraform apply tfplan
else
  echo "⚠ No var file at $VAR_FILE — running plan/apply with defaults"
  terraform plan -out=tfplan
  terraform apply tfplan
fi
