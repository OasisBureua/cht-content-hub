# infra/modules/s3/

S3 bucket module.

## Inputs

- Bucket name (`cht-content-hub-{env}-{purpose}` — e.g. `cht-content-hub-prod-frontend`, `cht-content-hub-prod-render-output`)
- Encryption (SSE-KMS using project KMS key)
- Lifecycle policies (transition to Glacier, expiration)
- Versioning (enabled for state buckets, lifecycle-managed for artifacts)
- Public access block (default: all blocked; CloudFront-served buckets use OAC)

## Outputs

- Bucket ARN
- Bucket regional domain name (for CloudFront origin)

## Notes

- Frontend bucket served via CloudFront with Origin Access Control (no public read).
- Render-output and report buckets use signed URLs for browser delivery.
- Lifecycle: transition to Glacier after 90 days, expire after 365 days for artifact buckets. State buckets keep indefinitely.
