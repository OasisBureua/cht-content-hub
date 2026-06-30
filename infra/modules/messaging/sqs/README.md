# infra/modules/messaging/sqs/

SQS queue module with dead-letter queue.

## Inputs

- Queue name (`cht-content-hub-{env}-{purpose}`)
- Visibility timeout (must be ≥ consumer Lambda timeout)
- Message retention (default 14 days)
- KMS key for encryption
- DLQ max-receive count (default 3)
- Alarm threshold on DLQ depth (default > 0)

## Outputs

- Queue URL + ARN
- DLQ URL + ARN

## Notes

- Every queue has a paired DLQ. Failed jobs land there and fire a CloudWatch alarm.
- Used by sync Lambdas and the cache-clear orchestrator for queued/long-running work.
