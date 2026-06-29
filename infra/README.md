# infra/

All AWS infrastructure-as-code for `cht-content-hub`. Terraform.

## Layout

- `environments/<env>/` — environment-specific configuration. One subdirectory per environment (`dev`, `staging`, `prod`). Each references modules from `modules/` and injects environment-specific values.
- `modules/<resource>/` — reusable Terraform modules, one per AWS resource type or pattern. Composed by environment configs.
- `shared/` — account-wide resources that don't belong to a single environment (VPC reference, account-level IAM, Route53 zone reference).

## Tooling

- **Terraform** for all AWS resources
- **State backend:** S3 (`cht-content-hub-terraform-state-<region>`) + DynamoDB lock table (`cht-content-hub-terraform-locks`)
- **CI/CD:** GitHub Actions workflows in `.github/workflows/` deploy per-environment via OIDC-assumed role `GitHubActions-CHT-ContentHub`
- **Reference:** `cht-platform-tool/infrastructure/terraform/` is the layout template. Modules mirror that structure with `cht-content-hub-*` resource naming.

## Conventions

- One environment per directory under `environments/`. No environment-conditional logic inside modules — modules are pure, environments compose them.
- Module names match the AWS service name (e.g. `aurora/`, `rds/`, `cognito/`, `eventbridge/`) for greppability.
- Secrets never live in this directory. All secrets are in AWS Secrets Manager and referenced by ARN.
- Resource naming follows `cht-content-hub-*` prefix, mirroring the `cht-platform-*` pattern in the sibling repo.
