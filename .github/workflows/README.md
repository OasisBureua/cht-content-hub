# .github/workflows/

CI/CD pipelines. Following the pattern proven by `cht-platform-tool`.

Likely shape:

| Workflow | Trigger | Purpose |
|---|---|---|
| `pr-validation.yml` | Pull requests | Lint (ruff, mypy), unit tests, Terraform validate, Terraform plan against dev |
| `deploy-dev.yml` | Push to `feature/**` or `develop` | Deploy to dev environment |
| `deploy-staging.yml` | Push to `staging` branch | Deploy to staging environment |
| `deploy-prod.yml` | Push to `release/**` or `v*` tags, manual | Deploy to prod (with manual approval gate) |
| `rollback.yml` | Manual | Roll back ECS services and disable EventBridge rules |

## Authentication

GitHub Actions assumes the IAM role `GitHubActions-CHT-ContentHub` via OIDC. No long-lived AWS keys stored in GitHub Secrets. Bootstrap pattern mirrors `cht-platform-tool/infrastructure/aws-github-oidc-setup.sh`.

## Environments

GitHub Environment secrets per `dev`, `staging`, `prod`. Branch protection rules gate deploys to staging and prod.
