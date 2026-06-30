# CI/CD

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-validation.yml` | Pull requests | Terraform validate |

Application CI (Python tests, Docker builds) will be added when `backend/` and `worker/` code lands.

## Local verification

```bash
./verify.sh
```

## Manual deploy

```bash
./scripts/deploy-primary.sh dev
```

See [docs/engineering/deployment.md](../docs/engineering/deployment.md).
