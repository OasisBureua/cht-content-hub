# infra/modules/messaging/eventbridge/

EventBridge Scheduler rule module. Cron or rate-based trigger that invokes a Lambda directly or a Step Function.

## Inputs

- Rule name (`cht-content-hub-{domain}-{function}-schedule`)
- Schedule expression (cron or rate)
- Target ARN (Lambda or Step Function)
- Retry policy (default: 2 retries with 60s backoff)
- Dead-letter SQS queue ARN (for failed deliveries)

## Outputs

- Rule ARN
- IAM role ARN used to invoke the target

## Notes

- Replaces APScheduler from the legacy MediaHub ECS worker.
- One rule per scheduled job. No rule sharing.
