# infra/modules/lambda/

Reusable Lambda module.

## Inputs

- Function name (prefix `cht-content-hub-` added by the module)
- Handler path, runtime (Python 3.12 default), memory, timeout
- Environment variables
- Trigger type (EventBridge rule ARN, SQS queue ARN, or direct invoke)
- VPC config (when the Lambda needs producer DB access — required for tagging, sync, cache_clear)
- Secrets Manager paths for environment-bound secrets

## Outputs

- Function ARN
- Log group name (`/aws/lambda/cht-content-hub-*`)
- Execution role ARN

## Responsibilities

- Function creation, deployment package S3 reference
- IAM execution role with least-privilege policy
- CloudWatch log group with retention policy per environment
- SNS failure topic subscription (`cht-content-hub-{env}-alerts-warning`)
- Optional reserved concurrency setting (used =1 for tagging Lambdas)

## Lambda Layer support

`post_tagger` is published as a versioned Lambda Layer by a separate Terraform resource. This module accepts a list of layer ARNs in its input.
