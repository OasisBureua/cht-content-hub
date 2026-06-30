# infra/modules/messaging/

Event and queue infrastructure.

- `eventbridge/` — EventBridge Scheduler rule module (replaces APScheduler)
- `sqs/` — SQS queue + DLQ module
- `sns-alerts/` — SNS topics for alarms and on-call notification
