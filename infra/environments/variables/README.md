# infra/environments/variables/

Terraform variable files, one per environment.

- `dev.tfvars` — developer values (small instance sizes, single-AZ, relaxed retention)
- `prod.tfvars` — production values (Aurora Global, multi-AZ Fargate, full retention)

Referenced from the region directories at apply time:

```
cd ../us-east-1
terraform apply -var-file=../variables/dev.tfvars
```

Sensitive values (DB passwords, API keys) are not stored here — they live in AWS Secrets Manager and are referenced by ARN.
