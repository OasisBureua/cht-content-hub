# VPC-colocated deployment (locked)

**Decision:** Content Hub producer runs **inside the CHT platform VPC** (shared subnets/NAT) with its **own ECS cluster**, dedicated RDS, and public API ALB. CHT integrates over HTTP only — it calls `CONTENTHUB_BASE_URL`, not shared compute.

**Status:** Approved — June 2026  
**Rejected:** Sharing CHT’s ECS cluster (separate blast radius and deploy lifecycle for producer).

---

## Architecture

```text
┌── CHT VPC (cht-platform-tool Terraform) ─────────────────────────────┐
│                                                                      │
│  CloudFront/S3  contenthub.*     ALB  cht-platform-backend           │
│  (consumer SPA)                  (platform API)                      │
│                                                                      │
│  ┌── CHT ECS cluster ─────────────────────────────────────────────┐ │
│  │  cht-platform-backend tasks                                    │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌── Content Hub ECS cluster (contenthub-{env}-cluster) ──────────┐ │
│  │  contenthub-api tasks     ← producer API (this repo)           │ │
│  │  contenthub-worker tasks  ← optional bridge until Lambda       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  CHT Aurora (platform DB)            Producer RDS (content hub only) │
│  ElastiCache cht:catalog:*           never shared with CHT backend │
│                                                                      │
│  Internet ALB  devhub.* / contenthub.*  → contenthub-api only        │
└──────────────────────────────────────────────────────────────────────┘

CHT backend  ──HTTP + X-API-Key──►  devhub.* / contenthub.* /api/public
              (CONTENTHUB_BASE_URL)    (no Postgres, no shared ECS cluster)
```

| Resource | Owner | Shared with CHT? |
|----------|-------|------------------|
| VPC, subnets, NAT | CHT platform | Yes |
| ECS cluster | Content Hub Terraform | **No** — `contenthub-dev-cluster` / `contenthub-cluster` |
| Platform ALB / CloudFront | CHT platform | No |
| Producer ALB | Content Hub Terraform | No |
| Platform Aurora | CHT platform | No |
| Producer RDS | Content Hub Terraform | No |

**Rule unchanged:** CHT backend never connects to producer Postgres. Catalog integration is HTTP + `X-API-Key` only.

---

## Terraform settings

In `dev.tfvars` / `prod.tfvars`:

```hcl
deploy_mode = "cht-vpc"

# From cht-platform-tool outputs (VPC + subnets only — no cluster ARN)
vpc_id             = "vpc-..."
private_subnet_ids = ["subnet-...", "subnet-..."]
public_subnet_ids  = ["subnet-...", "subnet-..."]
```

Terraform always creates:

- `contenthub-dev-cluster` (dev) or `contenthub-cluster` (prod)
- `/ecs/contenthub-dev` or `/ecs/contenthub` log group

No `ecs_cluster_arn` / `ecs_cluster_name` in tfvars.

---

## Collect networking from CHT platform

From a machine with AWS CLI + access to the CHT Terraform state, read outputs from `cht-platform-tool`:

| Output | Used for |
|--------|----------|
| `vpc_id` | All producer modules |
| Private subnet IDs | ECS tasks, RDS |
| Public subnet IDs | Internet-facing producer ALB |

Subnet IDs are often tagged `Tier=private` / `Tier=public` on the CHT VPC. If tags differ, set subnets manually in tfvars.

---

## DNS & TLS

| Environment | Producer API hostname | CHT `CONTENTHUB_BASE_URL` |
|-------------|----------------------|-------------------------|
| **Dev** | `devhub.communityhealth.media` | `https://devhub.communityhealth.media/api/public` |
| **Prod** | `contenthub.communityhealth.media` | `https://contenthub.communityhealth.media/api/public` |

Consumer/admin SPA hostnames are owned by **cht-platform-tool** (CloudFront). Producer API gets its own ALB + ACM cert on the hostnames above.

### Certificates

```bash
./scripts/request-certificate-devhub.sh
./scripts/request-certificate-contenthub.sh
./scripts/check-certificates-status.sh devhub
./scripts/verify-certificate.sh devhub
```

After ISSUED, set `acm_certificate_arn` in tfvars from `infrastructure/terraform/environments/variables/.cert-arns-*`.

### Route53 (Terraform)

With `manage_route53 = true` (default), Terraform creates a hosted zone for `api_domain` and an **A/alias** → producer ALB.

**Traffic path:** Route53 → ALB → ECS → RDS (until CloudFront + S3 frontend is added).

After `terraform apply`, delegate the subdomain in GoDaddy:

```bash
terraform output route53_nameservers
terraform output dns_delegation_hint
```

Add **NS** records for `devhub` (or `contenthub`) in the parent `communityhealth.media` zone — same pattern as CHT `devapp.communityhealth.media`.

---

## What we do not colocate

- **ECS cluster** — always Content Hub–owned
- **Producer database** — always a separate RDS instance
- **Sync Lambdas** — VPC-attached in same VPC; own IAM roles
- **Content Hub Redis** — not provisioned
- **GoTrue / JWT auth on producer** — retired; studio auth uses Cognito JWKS from CHT

---

## Standalone mode (not chosen)

Use only for a greenfield AWS account with no CHT platform:

```hcl
deploy_mode = "standalone"
# + own vpc module (not included — would need modules/networking/vpc)
```

Not supported out of the box in this repo today.

---

## Next infra steps

1. Copy `vpc_id` + subnet IDs from cht-platform-tool → `dev.tfvars`
2. Set secrets via `TF_VAR_public_api_key` etc.
3. Request ACM cert: `./scripts/request-certificate-devhub.sh`
4. `terraform apply` — creates Route53 zone + ALB alias (then delegate NS in GoDaddy)
5. `./scripts/deploy-primary.sh dev apply` — cluster, RDS, ALB, ECS API

See [contenthub-migration-plan.md](../contenthub-migration-plan.md) Phase 1.
