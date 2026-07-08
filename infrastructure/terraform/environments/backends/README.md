# Terraform remote state — Content Hub

Dedicated bucket **`cht-contenthub-terraform-state`** (separate from CHT platform and legacy MediaHub).

| Environment | State key | Hostname context |
| ----------- | --------- | ---------------- |
| dev         | `devhub/terraform.tfstate` | `devhub.communityhealth.media` |
| prod        | `contenthub/terraform.tfstate` | `contenthub.communityhealth.media` |

## One-time bucket setup

```bash
./scripts/bootstrap-terraform-state.sh
```

## Init before plan/apply

```bash
cd infrastructure/terraform/environments/us-east-1
terraform init -reconfigure -backend-config=../backends/us-east-1-dev.hcl
terraform plan -var-file=../variables/dev.tfvars
```

Or `./scripts/deploy-primary.sh dev` (init + plan + apply — **wait for ACM ISSUED before apply**).

**Important:** Always `-reconfigure` when switching between dev and prod in the same directory.
