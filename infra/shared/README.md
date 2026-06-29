# infra/shared/

Account-wide AWS resources that don't belong to a single environment.

Examples:
- VPC and subnet baseline
- Account-level IAM roles (e.g. cross-account assume roles, deploy roles)
- Route53 hosted zone if delegated from GoDaddy
- ACM certificates for `*.contenthub.communityhealth.media`
- Account-level CloudTrail and Config
