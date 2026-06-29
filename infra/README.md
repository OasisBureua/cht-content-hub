# infra/

All AWS infrastructure-as-code for ContentHub.

## Layout

- `environments/<env>/` — environment-specific configuration. One subdirectory per environment (dev, staging, prod). These reference modules from `modules/` and inject environment-specific values.
- `modules/<resource>/` — reusable IaC modules, one per AWS resource type or pattern. Composed by the environment configs.
- `shared/` — account-wide resources that don't belong to a single environment (VPC baseline, account-level IAM roles, base Route53 zones if applicable).

## Tool choice

Tool selection (Terraform vs. AWS CDK vs. Pulumi vs. SAM) is pending. The directory layout above works for all four.

Once the tool is picked, each module gets the tool-appropriate scaffold (`.tf` files for Terraform, `stacks/` for CDK, etc.).

## Conventions

- One environment per directory under `environments/`. No environment-conditional logic inside modules — modules are pure, environments compose them.
- Module names match the AWS service name (e.g. `aurora/`, `cognito/`, `eventbridge/`) for greppability.
- Secrets never live in this directory. All secrets are in AWS Secrets Manager and referenced by ARN.
