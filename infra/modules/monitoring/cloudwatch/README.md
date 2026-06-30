# infra/modules/monitoring/cloudwatch/

CloudWatch log groups, custom metrics, alarms, and dashboards for `cht-content-hub-*` resources.

Log group naming: `/ecs/cht-content-hub-*` and `/aws/lambda/cht-content-hub-*`.

Retention per environment: 7d for dev, 90d+ for prod.

Alarms publish to SNS topics `cht-content-hub-{env}-alerts-{critical,warning}`.
