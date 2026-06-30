# infra/modules/security/

Security and identity infrastructure.

- `cognito/` — Cognito user pool with `chm-*` groups
- `iam/` — project IAM roles and policies
- `kms/` — KMS keys for encryption (RDS, S3, SQS, Secrets Manager)
- `secrets-manager/` — Secrets Manager secrets and rotation
- `waf-cloudfront/` — WAF web ACL for the CloudFront distribution
