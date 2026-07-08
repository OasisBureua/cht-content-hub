# Terraform variable files

| File | Purpose |
|------|---------|
| `dev.tfvars.example` | Template — commit to git |
| `dev.github.tfvars` | Non-secret dev infra for GitHub Actions — commit to git |
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
| `cht_backend_security_group_id` | CHT `terraform output backend_security_group_id` (in-VPC path to Hub ALB) |
| `cht_nat_gateway_cidr_blocks` | CHT `terraform output nat_gateway_public_ips` as `/32` (ECS egress via public devhub URL) |
| `alb_allow_public_ingress` | `false` on dev with CHT SG and/or NAT CIDRs; `true` on prod until tightened |
| `enable_waf` | `true` on dev — regional WAF on API ALB |
| `api_domain` | `devhub.communityhealth.media` (dev) or `contenthub.communityhealth.media` (prod) |
| `acm_certificate_arn` | `.cert-arns-*` after cert is ISSUED |
| `api_image`, `worker_image` | ECR after first image push |
| `manage_route53` | Default `true` — creates hosted zone + ALB alias for `api_domain`; set `false` if DNS is manual |
| `public_api_key` | Must match CHT `CONTENTHUB_API_KEY` — use `TF_VAR_public_api_key` |
| `webhook_api_key` | ops-console — use `TF_VAR_webhook_api_key` |
| `jwt_secret` | Required by Terraform today — use `TF_VAR_jwt_secret` |
| `internal_cache_secret` | Shared with CHT cache clear — use `TF_VAR_internal_cache_secret` |

### Platform integrations (optional — LinkedIn/YouTube sync, AI insights)

Set in **gitignored** `dev.tfvars` (local) or GitHub Environment secrets → `TF_VAR_*` (CI).  
Stored in `contenthub-dev-app-secrets` JSON and injected into the API ECS task.

| Variable | Purpose |
|----------|---------|
| `linkedin_ads_client_id`, `linkedin_ads_client_secret`, `linkedin_ads_redirect_uri`, `linkedin_ads_scopes`, `linkedin_ad_account_id` | LinkedIn Ads report sync |
| `linkedin_client_id`, `linkedin_client_secret`, `linkedin_redirect_uri`, `linkedin_scopes`, `linkedin_org_urn` | LinkedIn organic (Lambdas / future) |
| `youtube_api_key`, `youtube_channel_id`, `youtube_channel_handle` | YouTube report sync |
| `openai_api_key`, `anthropic_api_key` | AI insights |
| `x_bearer_token`, `x_account_handle`, `wordpress_webhook_secret` | Optional integrations |

**Important:** Terraform manages the full Secrets Manager JSON. Fill these in `dev.tfvars` (or GitHub secrets) **before** `terraform apply`, or empty values will overwrite keys you added manually in AWS.

### Secrets (do not commit)

```bash
export TF_VAR_public_api_key="..."
export TF_VAR_webhook_api_key="..."
export TF_VAR_jwt_secret="..."
export TF_VAR_internal_cache_secret="..."
```

Then run `./scripts/deploy-primary.sh dev` or `prod`.

### Dev ALB lockdown (CHT consumer only)

When `alb_allow_public_ingress = false`, allow Hub traffic from:

1. **`cht_backend_security_group_id`** — in-VPC SG reference (future internal path)
2. **`cht_nat_gateway_cidr_blocks`** — CHT NAT `/32`s (ECS private subnet → public `devhub` URL today)

If NAT rules were added manually in AWS first, import before apply to avoid duplicates:

```bash
cd infrastructure/terraform/environments/us-east-1
terraform import 'module.alb_api.aws_vpc_security_group_ingress_rule.https_from_cidr["18.233.236.119/32"]' sgr-0a7f3de57bcc52529
terraform import 'module.alb_api.aws_vpc_security_group_ingress_rule.https_from_cidr["44.223.243.240/32"]' sgr-0fd65b645fedc51ba
```

Rule IDs change if rules are recreated — list with:

```bash
aws ec2 describe-security-group-rules --filters Name=group-id,Values=<api-alb-sg-id> \
  --query 'SecurityGroupRules[?IsEgress==`false` && FromPort==`443` && CidrIpv4!=`null`].[SecurityGroupRuleId,CidrIpv4]' --output table
```

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

# 5. Plan only until devhub ACM is ISSUED (apply blocked without acm_certificate_arn)
./scripts/deploy-primary.sh dev plan
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
