# services/step_functions/

Step Function state machine definitions for multi-step orchestration.

Per the migration plan: Step Functions are reserved for genuinely multi-step or parallel orchestration. Simple cron → single Lambda jobs use EventBridge → Lambda direct.

## Expected state machines (post-R1)

- `hcp_intel_orchestrator/` — 30-minute polling loop dispatching to per-source fetchers, persisting signals, running disambiguation
- `video_upload_pipeline/` — upload → metadata probe → Whisper transcribe → segment → ready-for-edit
- `cms_part_d_ingest/` — annual large-dataset ingest, runs on Fargate (too large for Lambda)

## Layout per state machine

```
<state_machine_name>/
├── definition.asl.json     # Amazon States Language definition
├── README.md               # Purpose, triggers, failure modes, runbook
└── tests/                  # Local validation tests
```

## Status

None defined yet — Round 1 dev work is all direct EventBridge → Lambda or SQS → Lambda. Step Functions arrive with the post-R1 HCP Intel and video pipeline work.
