# services/step_functions/

Step Function state machine definitions for multi-step orchestration.

Step Functions are reserved for genuinely multi-step or parallel orchestration. Simple cron → single Lambda jobs use EventBridge → Lambda direct.

Expected state machines:

- `hcp_intel_orchestrator/` — 30-minute polling loop that dispatches to per-source fetchers, persists signals, runs audit/disambiguation
- `video_upload_pipeline/` — upload → metadata probe → Whisper transcribe → segment → ready-for-edit
- `report_generation/` — collect data → render → QA → publish (post-rewrite)

## Layout per state machine

```
<state_machine_name>/
├── definition.asl.json     # Amazon States Language definition
├── README.md               # Purpose, triggers, failure modes, runbook
└── tests/                  # Local validation tests
```
