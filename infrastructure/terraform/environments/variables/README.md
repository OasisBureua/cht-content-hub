# Terraform variable files

## File roles

| File | Commit? | Contents |
|------|---------|----------|
| `dev.github.tfvars` / `prod.github.tfvars` | Yes | **All non-secret infra** — VPC, subnets, DR, feature flags, sizing. Used by CI and local scripts. |
| `dev.tfvars` / `prod.tfvars` | No (gitignored) | **Secrets** (`public_api_key`, …) + **optional local overrides** that win over `.github.tfvars`. |
| `*.tfvars.example` | Yes | Template for gitignored files (secrets + override examples only). |

## How scripts load var files

All deploy scripts use `scripts/terraform-var-files.sh`:

1. Always load `{env}.github.tfvars`
2. If `{env}.tfvars` exists, load it second (**overrides** duplicate keys)
3. CI (GitHub Actions) uses only `{env}.github.tfvars` + `TF_VAR_*` for secrets

Scripts: `deploy-primary.sh`, `deploy-api-service.sh`, `deploy-contenthub-infra-local.sh`, `deploy-contenthub-secondary.sh`, `drill-route53-failover.sh`.

## Route53 failover (test later)

Keep `enable_route53_failover = false` in tfvars during infra deploy. The Terraform **code** is ready; nothing activates until you run:

```bash
./scripts/arm-route53-failover.sh arm   # after ECS is up in use1 + use2 via CI
```

**Do not** set `enable_route53_failover = true` in tfvars and forget about it — if primary health checks fail before DR ECS exists, DNS flips to use2 and users get 503.

## Local failover drill (example overrides in prod.tfvars)

Only if arming via tfvars instead of the script (not recommended):

```hcl
# enable_route53_failover = true
```

ECS is **not** started by Terraform — use `deploy-prod.yml` / `ecs-update-service-images.sh`.

## Required fields

### Both environments

| Variable | Where to get it |
|----------|-----------------|
| `vpc_id`, `private_subnet_ids`, `public_subnet_ids` | cht-platform-tool Terraform outputs |
| `cht_backend_security_group_id` | CHT `terraform output backend_security_group_id` (in-VPC path to Hub ALB) |
| `cht_nat_gateway_cidr_blocks` | CHT `terraform output nat_gateway_public_ips` as `/32` (ECS egress via public devhub URL) |
| `alb_allow_public_ingress` | `false` on dev with CHT SG and/or NAT CIDRs; `true` on prod until tightened |
| `enable_waf` | `true` on dev — regional WAF on API ALB |
| `api_domain` | `devhub.communityhealth.media` (dev) or `contenthub.communityhealth.media` (prod) |
| `acm_certificate_arn` | `.cert-arns-*` after cert is ISSUED |
| `api_image` | ECR after first image push — dev: `contenthub-dev-api`, prod: `contenthub-api` |
| `manage_route53` | Default `true` — creates hosted zone + ALB alias for `api_domain`; set `false` if DNS is manual |
| `enable_route53_failover` | Keep `false`; arm later with `./scripts/arm-route53-failover.sh` |
| `dr_deploy_api_ecs_service` | Keep `false` — ECS via `deploy-prod.yml` (CI/CD) |
| `public_api_key` | Must match CHT `CONTENTHUB_API_KEY` — use `TF_VAR_public_api_key` or prod.tfvars |
| `webhook_api_key` | ops-console — use `TF_VAR_webhook_api_key` |
| `jwt_secret` | Required by Terraform today — use `TF_VAR_jwt_secret` |
| `internal_cache_secret` | Shared with CHT cache clear — use `TF_VAR_internal_cache_secret` |
| `secrets_replica_regions` | Prod only: `["us-east-2"]` — SM multi-region replicas on use1 secrets (CHT pattern) |

### Platform integrations (optional — LinkedIn/YouTube sync, AI insights)

Set in **gitignored** `dev.tfvars` / `prod.tfvars` (local) or GitHub Environment secrets → `TF_VAR_*` (CI).  
Stored in `contenthub-dev-app-secrets` JSON and injected into the API ECS task.

| Variable | Purpose |
|----------|---------|
| `linkedin_ads_client_id`, `linkedin_ads_client_secret`, `linkedin_ads_redirect_uri`, `linkedin_ads_scopes`, `linkedin_ad_account_id` | LinkedIn Ads report sync |
| `linkedin_client_id`, `linkedin_client_secret`, `linkedin_redirect_uri`, `linkedin_scopes`, `linkedin_org_urn` | LinkedIn organic (Lambdas / future) |
| `youtube_api_key`, `youtube_channel_id`, `youtube_channel_handle` | YouTube report sync |
| `openai_api_key`, `anthropic_api_key` | AI insights |
| `x_bearer_token`, `x_account_handle` | X/Twitter sync |
| `wordpress_webhook_secret` | WordPress webhook validation |

## Dev vs prod DR

**Dev is us-east-1 only.** Prod DR uses the same `prod.github.tfvars` / `prod.tfvars` with `dr_*` keys (CHT pattern) — apply via `./scripts/deploy-contenthub-secondary.sh`.

## First-time setup

```bash
# 1. Copy templates (if dev.tfvars / prod.tfvars don't exist)
cp dev.tfvars.example dev.tfvars
cp prod.tfvars.example prod.tfvars

# 2. Fill secrets in dev.tfvars / prod.tfvars
# 3. Non-secret values: edit dev.github.tfvars / prod.github.tfvars (or sync from team)
```

## ALB ingress (CHT consumer path)

When `alb_allow_public_ingress = false`, allow Hub traffic from:

1. **`cht_backend_security_group_id`** — in-VPC SG reference (future internal path)
2. **`cht_nat_gateway_cidr_blocks`** — CHT NAT `/32`s (ECS private subnet → public `devhub` URL today)

## Importing existing SG rules (dev)

If Terraform wants to recreate CHT NAT rules that already exist in AWS:

```bash
terraform import 'module.alb_api.aws_vpc_security_group_ingress_rule.https_from_cidr["18.233.236.119/32"]' sgr-0a7f3de57bcc52529
terraform import 'module.alb_api.aws_vpc_security_group_ingress_rule.https_from_cidr["44.223.243.240/32"]' sgr-0fd65b645fedc51ba
```
