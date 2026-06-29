# infra/modules/waf/

WAF web ACL module.

## Inputs

- Web ACL name (`cht-content-hub-{env}-acl`)
- Scope: `CLOUDFRONT` (for the SPA distribution) or `REGIONAL` (for the ALB)
- Managed rule sets: AWS Core, Known Bad Inputs, SQL Injection, Linux/Unix
- Custom rules: rate limiting per IP, allowlists for internal callers

## Outputs

- Web ACL ARN

## Notes

- One ACL per environment.
- CloudFront ACLs must be created in `us-east-1` regardless of distribution region.
