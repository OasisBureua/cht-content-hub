# infra/modules/monitoring/

Observability and compliance resources.

- `cloudwatch/` — log groups, custom metrics, alarms, dashboards
- `cloudtrail/` — account-level trail (likely reused from CHT setup; this is a thin reference if reuse, full provisioning if not)
- `guardduty/` — threat detection (likely reused from CHT setup)
- `aws-config/` — continuous compliance monitoring (likely reused from CHT setup)
