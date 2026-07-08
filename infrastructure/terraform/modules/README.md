# Terraform Modules — Content Hub

Headless **producer microservice** for CHT — api + worker + RDS + public API ALB.

**Architecture:** [docs/engineering/colocated-deployment.md](../../../docs/engineering/colocated-deployment.md)

```
modules/
├── networking/
│   ├── alb-api/             # Internet-facing ALB (CHT consumer, public URL)
│   ├── route53-api/         # Hosted zone + A/alias → ALB (until CloudFront + S3)
│   └── alb-internal/        # DEPRECATED — do not use for new envs
├── compute/
│   ├── ecs-api/             # contenthub-api (FastAPI :8000, autoscale)
│   └── ecs-worker/          # contenthub-worker (scheduler ×1)
├── database/
│   └── rds/                 # Content Hub Postgres (separate from CHT)
├── security/
│   ├── iam/
│   ├── secrets-manager/
│   └── waf-alb/             # Regional WAF on API ALB (dev/prod optional)
└── storage/ messaging/ …    # Post-MVP
```

**Not in MVP modules:** CloudFront, S3 frontend, ElastiCache (Content Hub Redis removed), NLB.

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
