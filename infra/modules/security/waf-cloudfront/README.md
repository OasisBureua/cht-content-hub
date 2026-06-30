# infra/modules/security/waf-cloudfront/

WAF web ACL module for the CloudFront distribution (CLOUDFRONT scope, deployed in `us-east-1`).

## Inputs

- Web ACL name (`cht-content-hub-{env}-cloudfront-acl`)
- Managed rule sets: AWS Core, Known Bad Inputs, SQL Injection, Linux/Unix
- Custom rules: rate limiting per IP, allowlists for internal callers

## Outputs

- Web ACL ARN

## Notes

- CloudFront ACLs must be in `us-east-1` regardless of distribution region.
