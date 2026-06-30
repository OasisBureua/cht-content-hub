# Deployment

> **Status:** Infrastructure-first. Deploy application services after Terraform layout is finalized.

## Current scope

| Layer | Status |
|-------|--------|
| Terraform modules | Copied from legacy MediaHub — needs review/adaptation |
| ECS API / worker | Modules exist — wire after infra decisions |
| RDS dev / Aurora prod | Defined in plan — apply via Terraform |
| Lambda sync pack | Planned under `sync/` — not deployed |
| Application images | Blocked — no `backend/` / `worker/` code yet |

### Certificates

```bash
./scripts/request-certificate-devhub.sh       # dev ALB TLS
./scripts/request-certificate-contenthub.sh # prod ALB TLS
./scripts/check-certificates-status.sh devhub
./scripts/verify-certificate.sh devhub        # exit 0 when ISSUED
```

Add `acm_certificate_arn` to `dev.tfvars` / `prod.tfvars` from `.cert-arns-*` after validation.

## Terraform

```bash
cp infrastructure/terraform/environments/variables/dev.tfvars.example \
   infrastructure/terraform/environments/variables/dev.tfvars

./scripts/deploy-primary.sh dev
```

## Verification

```bash
./verify.sh   # terraform validate
```

## Migration phases

See [contenthub-migration-plan.md](../contenthub-migration-plan.md):

- **Phase 1** — dev RDS + ECS + ALB (infra before code)
- **Phase 2** — studio API + admin UI
- **Phase 3** — prod Aurora + cutover
- **Phase 4** — decommission EC2 monolith
