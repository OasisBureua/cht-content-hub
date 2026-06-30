# Documentation

Operational docs for the CHT Content Hub producer service.

| Doc | Purpose |
|-----|---------|
| [engineering/getting-started.md](./engineering/getting-started.md) | Local development setup |
| [engineering/colocated-deployment.md](./engineering/colocated-deployment.md) | DNS, TLS, shared VPC + own cluster |
| [engineering/architecture.md](./engineering/architecture.md) | System design and CHT integration |
| [engineering/deployment.md](./engineering/deployment.md) | Staging and production deploys |
| [contenthub-migration-plan.md](./contenthub-migration-plan.md) | Canonical migration runbook |
| [contenthub-admin-architecture.md](./contenthub-admin-architecture.md) | Admin routes and Cognito group matrix |
| [cht-public-api-contract.md](./cht-public-api-contract.md) | CHT catalog API contract |
| [cache-sync-contract.md](./cache-sync-contract.md) | Lambda/worker → CHT cache clear |
| [WEBHOOK_API.md](./WEBHOOK_API.md) | ops-console webhook ingest |
| [Content_Hub_Migration_Plan.pdf](./Content_Hub_Migration_Plan.pdf) | PDF export of migration plan |

CI workflow details: [.github/CI_CD.md](../.github/CI_CD.md)

Infrastructure modules and Terraform layout: [infrastructure/README.md](../infrastructure/README.md)
