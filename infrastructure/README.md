# Content Hub Infrastructure

AWS infrastructure for the Content Hub **producer** service.

**Deployment mode (locked):** [VPC-colocated](../docs/engineering/colocated-deployment.md) — shared CHT VPC, **own** Content Hub ECS cluster, dedicated producer RDS + API ALB. CHT calls the producer over HTTP (`CONTENTHUB_BASE_URL`).

## Architecture

```text
CHT VPC
├── CHT ECS cluster
│   └── cht-platform-backend
├── Content Hub ECS cluster (contenthub-{env}-cluster)
│   ├── contenthub-api
│   └── contenthub-worker   (optional, worker_desired_count=0 by default)
├── Producer RDS            (never shared with CHT backend)
└── Internet ALB            devhub.* (dev) / contenthub.* (prod) → API
```

## Quick start

```bash
# 0. TLS (before HTTPS ALB)
./scripts/request-certificate-devhub.sh
./scripts/verify-certificate.sh devhub

# 1. Configure tfvars — vpc_id + subnets from cht-platform-tool outputs
cp infrastructure/terraform/environments/variables/dev.tfvars.example \
   infrastructure/terraform/environments/variables/dev.tfvars

# 2. Plan / apply (creates contenthub-dev-cluster + RDS + ALB)
./scripts/deploy-primary.sh dev
```

## Certificate scripts

| Script | Purpose |
|--------|---------|
| `request-certificate.sh devhub\|contenthub [region]` | Request ACM cert + save ARN |
| `request-certificate-devhub.sh` | Dev wrapper |
| `request-certificate-contenthub.sh` | Prod wrapper |
| `check-certificates-status.sh` | Show PENDING / ISSUED |
| `verify-certificate.sh` | Exit 0 only when ISSUED |

## State backend

Remote state lives in **`cht-contenthub-terraform-state`** (Content Hub–only bucket):

| Environment | Key |
|-------------|-----|
| dev | `devhub/terraform.tfstate` |
| prod | `contenthub/terraform.tfstate` |

Bootstrap once: `./scripts/bootstrap-terraform-state.sh`. See [environments/backends/README.md](terraform/environments/backends/README.md).

## GitHub Actions OIDC

Content Hub uses a **separate** deploy role from CHT (different repo + ECR/state prefixes).

```bash
chmod +x infrastructure/aws-github-oidc-setup.sh
./infrastructure/aws-github-oidc-setup.sh
# → paste AWS_ROLE_ARN into GitHub Environment "development"
```

Policy: [iam/github-actions-deploy-policy.json](iam/github-actions-deploy-policy.json). Full CI steps: [.github/CI_CD.md](../.github/CI_CD.md).

**Do not `terraform apply` until devhub ACM cert is ISSUED** (`acm_certificate_arn` in dev.tfvars).

## Modules

| Module | Purpose |
|--------|---------|
| `compute/ecs-cluster` | contenthub-{env}-cluster |
| `database/rds` | Producer Postgres (dev); Aurora module TBD Phase 3 |
| `compute/ecs-api` | contenthub-api |
| `compute/ecs-worker` | Optional bridge (`worker_desired_count = 0` default) |
| `networking/alb-api` | Public API ALB |
| `security/*` | IAM + Secrets Manager |

**Not deployed:** ElastiCache (retired per migration plan), standalone VPC.

## Related

- [docs/engineering/colocated-deployment.md](../docs/engineering/colocated-deployment.md)
- [docs/contenthub-migration-plan.md](../docs/contenthub-migration-plan.md)
