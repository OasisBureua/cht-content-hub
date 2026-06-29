# services/shared/observability/

Structured logging, metrics, and tracing.

- JSON-formatted logs written to CloudWatch with consistent field names across services
- Custom CloudWatch metrics for per-domain operations
- Distributed tracing setup (X-Ray or OpenTelemetry — tool TBD)
- Helpers for emitting structured error events to SNS alert topics
