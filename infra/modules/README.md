# infra/modules/

Reusable Terraform modules, organized by AWS service category. Mirrors the `cht-platform-tool` module taxonomy.

| Category | Modules |
|---|---|
| `compute/` | Lambda, Step Functions, ECS API |
| `database/` | RDS (dev), Aurora Global (prod) |
| `networking/` | VPC, ALB, CloudFront, Route53 |
| `security/` | Cognito, IAM, KMS, Secrets Manager, WAF |
| `storage/` | S3 |
| `messaging/` | EventBridge, SQS, SNS alerts |
| `monitoring/` | CloudWatch, CloudTrail, GuardDuty, Config |

## Conventions

- Module names match the AWS service name (e.g. `rds/`, `cognito/`, `eventbridge/`) for greppability.
- Modules are pure — no environment-conditional logic. Environments compose modules and pass environment-specific values.
- Module category dirs (e.g. `database/`) hold per-service subdirs (e.g. `database/rds/`, `database/aurora-global/`). Same pattern as `cht-platform-tool`.
