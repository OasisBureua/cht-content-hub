# infra/

All AWS infrastructure-as-code for `cht-content-hub`. Terraform.

## Layout

- `environments/<region>/` — region-specific Terraform composition (`us-east-1`, `us-east-2`). Each composes modules from `modules/` and selects a tfvars file at apply time.
- `environments/variables/` — environment-specific variable files (`dev.tfvars`, `prod.tfvars`) referenced by the region directories.
- `modules/<category>/<service>/` — reusable Terraform modules, organized by AWS service category (`compute`, `database`, `networking`, `security`, `storage`, `messaging`, `monitoring`).
- `shared/` — account-wide resources that don't belong to a single environment (VPC reference, account-level IAM, Route53 zone reference).

Mirrors the `cht-platform-tool` layout.

## Tooling

- **Terraform** for all AWS resources
- **State backend:** S3 (`cht-content-hub-terraform-state-<region>`) + DynamoDB lock table (`cht-content-hub-terraform-locks`)
- **CI/CD:** GitHub Actions workflows in `.github/workflows/` deploy per-environment via OIDC-assumed role `GitHubActions-CHT-ContentHub`

## Conventions

- Module category and service names match `cht-platform-tool` (`database/rds`, `database/aurora-global`, `compute/lambda`, etc.) for greppability.
- Modules are pure — no environment-conditional logic. Environments compose modules and pass values via tfvars.
- Secrets never live in this directory. All secrets are in AWS Secrets Manager and referenced by ARN.
