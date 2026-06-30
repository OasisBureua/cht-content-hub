# infra/environments/us-east-1/

Primary region composition. Hosts:

- Aurora Global writer cluster (prod) or RDS single-AZ (dev)
- ECS Fargate cluster + services (`cht-content-hub-api`)
- ALB
- CloudFront distribution
- Lambdas, EventBridge rules, SQS queues
- All per-environment Secrets Manager entries

Composes modules from `../../modules/` with values from `../variables/dev.tfvars` or `../variables/prod.tfvars`.
