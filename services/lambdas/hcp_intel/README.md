# services/lambdas/hcp_intel/

HCP Intelligence orchestrator + ingests.

## Status

**Deferred to post-R1.** Admin UI for HCP Intel stays on the legacy MediaHub at `/admin/studio/hcp-intel/*` until a future migration. Backend ingests migrate when that work is scheduled.

## Expected functions

| Function | Schedule | Executor |
|---|---|---|
| `hcp_intel_poll/` | 30m | SQS+Lambda |
| `hcp_intel_backfill_resolve/` | cron | Lambda |

Plus per-source fetchers (PubMed, ClinicalTrials, OpenAlex, Google News, Bluesky, YouTube) — coordinated by a Step Function defined in `../../step_functions/hcp_intel_orchestrator/`.

## Notes

- HCP Intel migrates as a unit, not piecemeal.
- Cross-domain bridges (`kol_hcp_matcher`, `clip_appearance`) need a defined sync strategy before this work begins.
- CMS Part D bulk ingest is too large for Lambda — runs on Fargate.
