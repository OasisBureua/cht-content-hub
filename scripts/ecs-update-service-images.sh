#!/usr/bin/env bash
# Point Content Hub ECS API service at a new container image without Terraform.
#
# Usage:
#   ./scripts/ecs-update-service-images.sh prod <image_tag>
#   ./scripts/ecs-update-service-images.sh dev <image_tag>
#   ./scripts/ecs-update-service-images.sh dr <image_tag>
#   API_IMAGE=... ./scripts/ecs-update-service-images.sh prod
set -euo pipefail

ENV="${1:-prod}"
IMAGE_TAG="${2:-}"

case "$ENV" in
  prod|platform)
    CLUSTER="contenthub-cluster"
    SERVICE="contenthub-api"
    AWS_REGION="${AWS_REGION:-us-east-1}"
    ECR_REPO="contenthub-api"
    ;;
  dev)
    CLUSTER="contenthub-dev-cluster"
    SERVICE="contenthub-dev-api"
    AWS_REGION="${AWS_REGION:-us-east-1}"
    ECR_REPO="contenthub-dev-api"
    ;;
  dr|use2|dr-use2)
    CLUSTER="contenthub-dr-use2-cluster"
    SERVICE="contenthub-dr-use2-api"
    AWS_REGION="${AWS_REGION:-us-east-2}"
    ECR_REPO="contenthub-api"
  ;;
  *)
    echo "Unknown environment: $ENV (use prod, dev, or dr)" >&2
    exit 1
    ;;
esac

ECR_REGISTRY="${ECR_REGISTRY:-233636046512.dkr.ecr.${AWS_REGION}.amazonaws.com}"
API_IMAGE="${API_IMAGE:-}"
if [ -z "$API_IMAGE" ]; then
  if [ -z "$IMAGE_TAG" ]; then
    echo "Usage: $0 <prod|dev|dr> <image_tag>" >&2
    echo "   or set API_IMAGE" >&2
    exit 1
  fi
  API_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
fi

CONTAINER_NAME="contenthub-api"

task_def_arn=$(aws ecs describe-services \
  --cluster "$CLUSTER" \
  --services "$SERVICE" \
  --region "$AWS_REGION" \
  --query 'services[0].taskDefinition' \
  --output text)

if [ "$task_def_arn" = "None" ] || [ -z "$task_def_arn" ]; then
  echo "ECS service not found: $CLUSTER / $SERVICE ($AWS_REGION)" >&2
  exit 1
fi

aws ecs describe-task-definition \
  --task-definition "$task_def_arn" \
  --region "$AWS_REGION" \
  --query 'taskDefinition' > /tmp/contenthub-ecs-task-def.json

jq --arg IMAGE "$API_IMAGE" --arg CONTAINER "$CONTAINER_NAME" \
  'del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)
   | .containerDefinitions = (.containerDefinitions | map(if .name == $CONTAINER then .image = $IMAGE else . end))' \
  /tmp/contenthub-ecs-task-def.json > /tmp/contenthub-ecs-task-def-new.json

new_task_def=$(aws ecs register-task-definition \
  --cli-input-json file:///tmp/contenthub-ecs-task-def-new.json \
  --region "$AWS_REGION" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE" \
  --task-definition "$new_task_def" \
  --force-new-deployment \
  --region "$AWS_REGION" \
  --no-cli-pager \
  --output text \
  --query 'service.serviceName'

echo "Updated $SERVICE → $API_IMAGE ($new_task_def)"

echo "Waiting for service to stabilize..."
aws ecs wait services-stable \
  --cluster "$CLUSTER" \
  --services "$SERVICE" \
  --region "$AWS_REGION"

echo "Done."
