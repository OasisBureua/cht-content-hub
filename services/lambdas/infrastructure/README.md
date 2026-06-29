# services/lambdas/infrastructure/

Cross-cutting operational Lambdas that don't belong to a single product domain.

Examples:
- Scheduled cleanup jobs (e.g. expired job-state pruning in DynamoDB)
- Webhook receivers from external systems (Jotform, etc.)
- Health-check probes
- On-demand admin operations
