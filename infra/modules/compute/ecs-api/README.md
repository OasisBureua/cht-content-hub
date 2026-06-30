# infra/modules/compute/ecs-api/

ECS Fargate cluster + service for the producer FastAPI surface (`cht-content-hub-api`).

## Inputs

- Cluster name (`cht-content-hub-{env}-cluster`)
- Task CPU + memory
- Service desired count + autoscaling thresholds
- Container image (from ECR `cht-content-hub-api:<tag>`)
- ALB target group ARN
- Task execution + task role ARNs
- VPC + subnet IDs
- Environment variables + Secrets Manager references

## Outputs

- Cluster ARN
- Service ARN
- Task definition ARN
