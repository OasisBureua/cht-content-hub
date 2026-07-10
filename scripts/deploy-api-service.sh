#!/usr/bin/env bash
# Build, push, and start the contenthub-api ECS service (after infra-only apply).
#
# Var files: {env}.github.tfvars + {env}.tfvars (secrets/overrides, optional).
#
# Prerequisite: infra applied with deploy_api_ecs_service = false
#
# Usage:
#   export TF_VAR_public_api_key=...   # if no {env}.tfvars
#   ./scripts/deploy-api-service.sh prod
#   ./scripts/deploy-api-service.sh prod 1.0.0   # explicit image tag
set -euo pipefail

ENV="${1:-prod}"
TAG="${2:-}"

case "$ENV" in
  dev|prod) ;;
  *)
    echo "Usage: ./scripts/deploy-api-service.sh [dev|prod] [IMAGE_TAG]"
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$REPO_ROOT/infrastructure/terraform/environments/us-east-1"
BACKEND_CONFIG="$REPO_ROOT/infrastructure/terraform/environments/backends/us-east-1-${ENV}.hcl"

# shellcheck source=scripts/terraform-var-files.sh
source "$REPO_ROOT/scripts/terraform-var-files.sh"
terraform_var_files_init "$ENV"

VAR_FILES=()
for arg in "${TF_VAR_FILE_ARGS[@]}"; do
  base="$(basename "${arg#-var-file=}")"
  VAR_FILES+=(-var-file="../variables/$base")
done

ECR_REPO="contenthub-api"
if [ "$ENV" = "dev" ]; then
  ECR_REPO="contenthub-dev-api"
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
if [ -z "$TAG" ]; then
  TAG="$(./scripts/next-ecr-image-tag.sh "$ECR_REPO" "$AWS_REGION")"
fi

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
API_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${TAG}"

echo "Content Hub — deploy API ECS service ($ENV)"
echo "Var files: ${TF_GITHUB_VAR_FILE##*/}$([ -f "$TF_LOCAL_VAR_FILE" ] && echo " + ${TF_LOCAL_VAR_FILE##*/}")"
echo "Image: $API_IMAGE"
echo ""

./scripts/build-images.sh "$TAG"
./scripts/push-images.sh "$TAG" "$AWS_REGION" "$ENV"

cd "$TF_DIR"
terraform init -reconfigure -backend-config="$BACKEND_CONFIG"

echo ""
echo "Creating ECS service + autoscaling (deploy_api_ecs_service=true)..."
terraform apply \
  "${VAR_FILES[@]}" \
  -var="api_image=${API_IMAGE}" \
  -var="deploy_api_ecs_service=true" \
  -auto-approve

CLUSTER="$(terraform output -raw cluster_name)"
SERVICE="$(terraform output -raw api_service_name)"

if [ -n "$SERVICE" ] && [ "$SERVICE" != "null" ]; then
  echo ""
  echo "Waiting for ECS service stable..."
  aws ecs wait services-stable \
    --cluster "$CLUSTER" \
    --services "$SERVICE" \
    --region "$AWS_REGION"
  echo "ECS service $SERVICE is stable"
fi

API_DOMAIN="$(read_tfvar api_domain || true)"
if [ -n "$API_DOMAIN" ]; then
  echo ""
  echo "Smoke: ./scripts/smoke.sh https://${API_DOMAIN}"
fi
