# infra/modules/compute/

Compute resources: Lambda, Step Functions, ECS.

- `ecs-api/` — Fargate cluster + service for the producer FastAPI surface
- `lambda/` — reusable Lambda function module
- `step-functions/` — state machine module
