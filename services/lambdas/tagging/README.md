# services/lambdas/tagging/

Lambdas for content tagging.

Expected functions:

- `content_tagger/` — daily cron, re-derives content tags from clip title + ai_summary + description
- `playlist_doctor_tagger/` — daily cron, ingests YouTube playlist titles to write `doctor:` tags down through shoots → clips → posts
- `post_tagger_lambda/` — invoked on post upload, runs the canonical `scan_text_for_tags` primitive

Dormant (decision pending):
- `shoot_tag_derivation/`
- `shoot_tag_distribution/`
