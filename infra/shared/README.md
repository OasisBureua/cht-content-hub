# infra/shared/

Account-wide AWS resources that don't belong to a single environment.

Examples:
- VPC reference (data source — VPC may be shared with `cht-platform-tool` or provisioned separately)
- Account-level IAM (deploy roles, OIDC provider)
- Route53 hosted zone reference (if delegated from GoDaddy)
- ACM certificate for `*.contenthub.communityhealth.media` (created in `us-east-1` for CloudFront)
- Account-level CloudTrail and Config (likely reuse from CHT account-level setup, not provisioned here)
