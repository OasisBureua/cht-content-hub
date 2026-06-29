# services/lambdas/

Event-driven AWS Lambdas, grouped by domain. One directory per function.

## Layout

```
lambdas/
├── tagging/                 # Content tagging
├── video/                   # Video / clip pipeline
├── reports/                 # Report generation
├── social/                  # Social platform publishing
├── hcp_intel/               # HCP Intel & attribution
└── infrastructure/          # Cross-cutting operational Lambdas
```

## Per-Lambda layout

Each Lambda is a self-contained directory:

```
<lambda_name>/
├── handler.py          # AWS Lambda entry point — minimal, calls into logic.py
├── logic.py            # Business logic, testable in isolation
├── pyproject.toml      # Lambda-specific dependencies (kept minimal)
├── README.md           # Purpose, trigger, inputs/outputs, runbook
└── tests/
    ├── test_logic.py
    └── fixtures/
```

The directory name is the Lambda's deployed name in AWS (with a `contenthub-` prefix added at deploy time).

## Conventions

- Handlers are thin: parse event, call logic, format response. No business logic in handlers.
- Logic functions are pure where possible — easier to test, easier to invoke from other contexts.
- Shared code is imported from `services/shared/` and vendored into the deployment package at build time.
- Each Lambda's README documents: what triggers it, what inputs it expects, what it produces, how to debug, how to manually invoke.
