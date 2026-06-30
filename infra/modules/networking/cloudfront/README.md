# infra/modules/networking/cloudfront/

CloudFront distribution for the Content Hub SPA.

## Inputs

- Distribution name (`cht-content-hub-{env}-distribution`)
- Origin: S3 bucket (frontend SPA) via Origin Access Control
- Aliases: `contenthub.communityhealth.media` (prod), `dev.contenthub.communityhealth.media` (dev)
- ACM certificate ARN (must be in `us-east-1` regardless of distribution region)
- Behaviors:
  - `/` → S3 origin (SPA)
  - `/api/*` → ALB origin (forwards to `cht-content-hub-api` for `/api/public/*` and `/api/admin/studio/*`; to `cht-platform-backend` for `/api/admin/platform/*`)
- WAF web ACL association (CloudFront scope)
- Logging to a separate S3 bucket

## Outputs

- Distribution domain (`d123abc.cloudfront.net`)
- Distribution ID

## Notes

Mirrors the `testapp.communityhealth.media` pattern from `cht-platform-tool` (CloudFront → S3 SPA, confirmed live).
