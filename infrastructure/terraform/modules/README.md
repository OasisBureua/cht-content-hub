# Terraform Modules — MediaHub

Headless **producer microservice** for CHT — api + worker + RDS + public API ALB.

**Architecture:** [docs/mediahub-architecture.md](../../../docs/mediahub-architecture.md)

```
modules/
├── networking/
│   ├── alb-api/             # Internet-facing ALB (CHT consumer, public URL)
│   └── alb-internal/        # DEPRECATED — do not use for new envs
├── compute/
│   ├── ecs-api/             # mediahub-api (FastAPI :8000, autoscale)
│   └── ecs-worker/          # mediahub-worker (scheduler ×1)
├── database/
│   └── rds/                 # MediaHub Postgres (separate from CHT)
├── security/
│   ├── iam/
│   └── secrets-manager/
└── storage/ messaging/ …    # Post-MVP
```

**Not in MVP modules:** CloudFront, S3 frontend, ElastiCache (MediaHub Redis removed), NLB.

## Deployment modes

| Mode | VPC | ECS cluster | Use when |
| ---- | --- | ----------- | -------- |
| **cht-vpc** | CHT VPC + public subnets for ALB | Own — `contenthub-{env}-cluster` | Recommended |
| **standalone** | Own VPC | Own cluster | Greenfield account |

## Data flow

```text
Route53 → alb-api → ecs-api → RDS
              ↑
         CHT (API key)

ecs-worker → RDS
          → CHT cache clear
```
