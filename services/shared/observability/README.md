# services/shared/observability/

Structured logging, metrics, and tracing.

- JSON-formatted logs written to CloudWatch with consistent field names across services
- Custom CloudWatch metrics for per-domain operations (sync job duration, cache invalidation latency, tagging throughput)
- Distributed tracing — tool TBD (X-Ray or OpenTelemetry)
- Helpers for emitting structured error events to SNS alert topics (`cht-content-hub-{env}-alerts-critical`, `-warning`)
