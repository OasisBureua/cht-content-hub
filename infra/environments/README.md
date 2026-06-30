# infra/environments/

Per-region Terraform composition, mirroring the `cht-platform-tool` layout.

| Directory | Purpose |
|---|---|
| `us-east-1/` | Primary region. Hosts the writer Aurora cluster, ECS services, ALB, CloudFront. |
| `us-east-2/` | Disaster recovery region. Hosts the reader Aurora cluster for Aurora Global failover. |
| `variables/` | Environment-specific variable files referenced by the region directories. |

## Variable files

| File | Use |
|---|---|
| `variables/dev.tfvars` | Developer-mode values. Used when running Terraform against the dev RDS instance and dev ECS task. |
| `variables/prod.tfvars` | Production values. Used by the deploy pipeline targeting the prod stack. |

Each region directory composes modules from `../modules/` and selects its tfvars file at apply time:

```
terraform apply -var-file=../variables/dev.tfvars
terraform apply -var-file=../variables/prod.tfvars
```
