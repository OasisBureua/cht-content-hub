# infra/modules/eventbridge/

EventBridge rule module. Cron or pattern trigger that invokes a Lambda or Step Function. Inputs: schedule expression, target ARN, retry policy. Outputs: rule ARN.
