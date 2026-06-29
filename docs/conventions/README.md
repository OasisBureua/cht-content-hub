# docs/conventions/

Code conventions, naming conventions, PR conventions.

Includes (or will include):
- Lambda naming: `contenthub-<domain>-<function>` (e.g. `contenthub-social-linkedin-thumbnail-refresh`)
- EventBridge rule naming: `contenthub-<domain>-<function>-schedule`
- S3 bucket naming: `contenthub-<env>-<purpose>` (e.g. `contenthub-prod-render-output`)
- DynamoDB table naming: `contenthub-<env>-<purpose>`
- Aurora schema names: `<domain>` (e.g. `hcp_intel`, `tagging`)
- PR description format
- Conventional Commits enforcement
