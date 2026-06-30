# infra/modules/messaging/sns-alerts/

SNS topics for alarms and on-call notification.

Standard topics:
- `cht-content-hub-{env}-alerts-critical`
- `cht-content-hub-{env}-alerts-warning`

Email subscriptions added per environment via tfvars.
