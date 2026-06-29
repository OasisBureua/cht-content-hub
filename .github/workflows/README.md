# .github/workflows/

CI/CD pipelines.

Pending initial pipeline scope confirmation. Likely shape:

1. `ci.yml` — runs on every PR: lint (ruff, mypy), unit tests, IaC validation
2. `deploy-staging.yml` — runs on merge to `develop`: deploys to staging environment
3. `deploy-prod.yml` — runs on merge to `main` or release tag: deploys to prod (with manual approval gate)

Workflows will use OIDC for AWS authentication (no long-lived access keys committed).
