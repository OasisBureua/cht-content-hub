#!/usr/bin/env bash
# Tag and push contenthub-api to ECR.
#
# Usage:
#   ./scripts/push-images.sh [VERSION] [AWS_REGION] [ENV]
#
# ENV selects the ECR repository and rolling alias:
#   dev  → contenthub-dev-api + dev-latest
#   prod → contenthub-api + prod-latest
#
# Examples:
#   ./scripts/push-images.sh 1.0.0 us-east-1 dev
#   TAG=$(./scripts/next-ecr-image-tag.sh contenthub-api us-east-1)
#   ./scripts/push-images.sh "$TAG" us-east-1 prod
set -euo pipefail

VERSION="${1:-dev-latest}"
AWS_REGION="${2:-us-east-1}"
ENV="${3:-dev}"

case "$ENV" in
  dev)
    ECR_REPO="contenthub-dev-api"
    ENV_TAG="dev-latest"
    ;;
  prod)
    ECR_REPO="contenthub-api"
    ENV_TAG="prod-latest"
    ;;
  *)
    echo "❌ Unknown ENV: $ENV (use dev or prod)"
    exit 1
    ;;
esac

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_URI="${ECR_REGISTRY}/${ECR_REPO}"

ensure_ecr_repo() {
  local name="$1"
  if ! aws ecr describe-repositories --repository-names "$name" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "📦 Creating ECR repository: $name"
    aws ecr create-repository --repository-name "$name" --region "$AWS_REGION" >/dev/null
  fi
}

echo "🚀 Pushing contenthub-api to ECR"
echo "Version:   $VERSION"
echo "Region:    $AWS_REGION"
echo "Repo:      $ECR_REPO"
echo "Env tag:   $ENV_TAG"
echo ""

ensure_ecr_repo "$ECR_REPO"

echo "🔐 Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"
echo ""

if ! docker image inspect "contenthub-api:${VERSION}" >/dev/null 2>&1; then
  echo "❌ Local image contenthub-api:${VERSION} not found."
  echo "   Run: ./scripts/build-images.sh ${VERSION}"
  exit 1
fi

echo "📤 Pushing contenthub-api..."
docker tag "contenthub-api:${VERSION}" "${ECR_URI}:${VERSION}"
docker tag "contenthub-api:${VERSION}" "${ECR_URI}:${ENV_TAG}"
docker push "${ECR_URI}:${VERSION}"
docker push "${ECR_URI}:${ENV_TAG}"
echo "✅ ${ECR_URI}:${ENV_TAG}"
echo ""
echo "Update infrastructure/terraform/environments/variables/${ENV}.tfvars:"
echo "  api_image = \"${ECR_URI}:${VERSION}\""
echo ""
echo "Next: ./scripts/deploy-primary.sh ${ENV}"
