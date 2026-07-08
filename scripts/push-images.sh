#!/usr/bin/env bash
# Tag and push contenthub-api + contenthub-worker to ECR.
#
# Usage:
#   ./scripts/push-images.sh [VERSION] [AWS_REGION] [ENV]
#
# Examples:
#   ./scripts/push-images.sh dev-latest us-east-1 dev
#   ./scripts/push-images.sh $(git rev-parse --short HEAD) us-east-1 dev
set -euo pipefail

VERSION="${1:-dev-latest}"
AWS_REGION="${2:-us-east-1}"
ENV="${3:-dev}"

case "$ENV" in
  dev) ENV_TAG="dev-latest" ;;
  prod) ENV_TAG="prod-latest" ;;
  *)
    echo "❌ Unknown ENV: $ENV (use dev or prod)"
    exit 1
    ;;
esac

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_API="${ECR_REGISTRY}/contenthub-api"
ECR_WORKER="${ECR_REGISTRY}/contenthub-worker"

ensure_ecr_repo() {
  local name="$1"
  if ! aws ecr describe-repositories --repository-names "$name" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "📦 Creating ECR repository: $name"
    aws ecr create-repository --repository-name "$name" --region "$AWS_REGION" >/dev/null
  fi
}

echo "🚀 Pushing Content Hub images to ECR"
echo "Version:   $VERSION"
echo "Region:    $AWS_REGION"
echo "Env tag:   $ENV_TAG"
echo ""

ensure_ecr_repo contenthub-api
ensure_ecr_repo contenthub-worker

echo "🔐 Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"
echo ""

for LOCAL_NAME in contenthub-api contenthub-worker; do
  if ! docker image inspect "${LOCAL_NAME}:${VERSION}" >/dev/null 2>&1; then
    echo "❌ Local image ${LOCAL_NAME}:${VERSION} not found."
    echo "   Run: ./scripts/build-images.sh ${VERSION}"
    exit 1
  fi
done

push_image() {
  local local_name="$1"
  local ecr_uri="$2"
  echo "📤 Pushing ${local_name}..."
  docker tag "${local_name}:${VERSION}" "${ecr_uri}:${VERSION}"
  docker tag "${local_name}:${VERSION}" "${ecr_uri}:${ENV_TAG}"
  docker push "${ecr_uri}:${VERSION}"
  docker push "${ecr_uri}:${ENV_TAG}"
  echo "✅ ${ecr_uri}:${ENV_TAG}"
  echo ""
}

push_image contenthub-api "$ECR_API"
push_image contenthub-worker "$ECR_WORKER"

echo "✅ Push complete."
echo ""
echo "Update infrastructure/terraform/environments/variables/${ENV}.tfvars:"
echo "  api_image    = \"${ECR_API}:${ENV_TAG}\""
echo "  worker_image = \"${ECR_WORKER}:${ENV_TAG}\""
echo ""
echo "Next:"
echo "  ./scripts/deploy-primary.sh ${ENV}"
echo "  ./scripts/smoke.sh https://devhub.communityhealth.media   # after DNS + apply"
