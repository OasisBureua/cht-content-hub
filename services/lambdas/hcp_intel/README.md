# services/lambdas/hcp_intel/

Lambdas for HCP Intelligence and attribution.

HCP Intel is the largest single migration unit. Decomposes into 7 functional clusters:

1. Orchestration core (likely Step Function — see `services/step_functions/hcp_intel_orchestrator/`)
2. NPI resolution and HCP roster management
3. External data ingests (CMS, NIH, OpenAlex) — mixed Lambda + Fargate (CMS Part D is too large for Lambda)
4. Webinar attendance and engagement signals
5. Source-specific fetchers (PubMed, ClinicalTrials, OpenAlex, Google News, Bluesky, YouTube)
6. Output products (rankings, AI briefs, attribution math)
7. Audit and maintenance

Sequencing: HCP Intel migrates as a unit, not piecemeal. Cross-domain bridges (`kol_hcp_matcher`, `clip_appearance`) need a defined sync strategy before this work begins.
