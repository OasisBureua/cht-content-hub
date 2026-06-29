# services/lambdas/reports/

Lambdas for report generation.

**Note:** the existing PPTX-based pipeline is a full-rewrite candidate, not a migration target. HTML generation is the working alternative. Lambdas here will be defined after the rewrite direction is confirmed.

Likely shape post-rewrite:
- `report_generate/` — produce HTML report from structured data
- `report_pdf_export/` — optional PDF export via headless Chromium (may need Fargate depending on size)
