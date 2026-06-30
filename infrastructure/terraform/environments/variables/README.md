# Terraform variable files

| File | Purpose |
|------|---------|
| `dev.tfvars.example` | Template — commit to git |
| `prod.tfvars.example` | Template — commit to git |
| `dev.tfvars` | Your dev values — **gitignored** |
| `prod.tfvars` | Your prod values — **gitignored** |
| `.cert-arns-devhub` | Written by `request-certificate-devhub.sh` |
| `.cert-arns-contenthub` | Written by `request-certificate-contenthub.sh` |

## Required fields

### Both environments

| Variable | Where to get it |
|----------|-----------------|
| `vpc_id`, `private_subnet_ids`, `public_subnet_ids` | cht-platform-tool Terraform outputs |
| `api_domain` | `devhub.communityhealth.media` (dev) or `contenthub.communityhealth.media` (prod) |
| `acm_certificate_arn` | `.cert-arns-*` after cert is ISSUED |
| `api_image`, `worker_image` | ECR after first image push |
| `public_api_key` | Must match CHT `MEDIAHUB_API_KEY` — use `TF_VAR_public_api_key` |
| `webhook_api_key` | ops-console — use `TF_VAR_webhook_api_key` |
| `jwt_secret` | Required by Terraform today — use `TF_VAR_jwt_secret` |
| `internal_cache_secret` | Shared with CHT cache clear — use `TF_VAR_internal_cache_secret` |

### Secrets (do not commit)

```bash
export TF_VAR_public_api_key="..."
export TF_VAR_webhook_api_key="..."
export TF_VAR_jwt_secret="..."
export TF_VAR_internal_cache_secret="..."
```

Then run `./scripts/deploy-primary.sh dev` or `prod`.

**Dev is us-east-1 only.** Multi-region DR (`environments/us-east-2/`) is prod Phase 3b — not used for dev.

## Setup checklist

```bash
# 1. Copy templates (if dev.tfvars / prod.tfvars don't exist)
cp dev.tfvars.example dev.tfvars
cp prod.tfvars.example prod.tfvars

# 2. Networking from CHT platform (vpc_id + subnets only)
# → paste into dev.tfvars from cht-platform-tool outputs

# 3. ACM cert
./scripts/request-certificate-devhub.sh
./scripts/verify-certificate.sh devhub
# → set acm_certificate_arn in dev.tfvars

# 4. Export secrets (see above)

# 5. Apply
./scripts/deploy-primary.sh dev
```

## Make scripts executable

```bash
chmod +x scripts/*.sh
chmod +x verify.sh
```

Or one file:

```bash
chmod +x scripts/request-certificate.sh
```
