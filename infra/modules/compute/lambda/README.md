# infra/modules/compute/lambda/

Reusable Lambda module.

## Inputs

- Function name (prefix `cht-content-hub-` added by the module)
- Handler path, runtime (Python 3.12 default), memory, timeout
- Environment variables
- Trigger type (EventBridge rule ARN, SQS queue ARN, or direct invoke)
- VPC config (when the Lambda needs producer DB access — required for tagging, sync, cache_clear)
- Secrets Manager paths for environment-bound secrets
- Reserved concurrency (optional, set =1 for tagging Lambdas)
- Lambda layer ARNs (used to attach the `post_tagger` foundation layer)

## Outputs

- Function ARN
- Log group name (`/aws/lambda/cht-content-hub-*`)
- Execution role ARN
