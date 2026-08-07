# WPR-14 (SCRUM-165) — Chaos + Load Burn-in Notes

## Burn-in status as of 2026-08-07

**Start date:** 2026-08-03 (Layer 2 hydration complete)
**Elapsed:** 4 days of real editorial traffic
**Required:** 1-week minimum per plan → complete on 2026-08-10

## Health signals (from `wpr14_burnin_health.py`)

| Signal | Status | Notes |
|---|---|---|
| Ingest queue depth | 0 visible / 0 in-flight | Clean |
| DLQ depth | **20 messages** | ⚠ **All from 2026-08-03**, none since. Stale artifact — see below |
| Ingest Lambda errors (24h) | 0 | Clean |
| Ops Lambda errors (24h) | 0 | Clean |
| Reconcile drift (posts) | 0 phantoms | Clean |
| Reconcile drift (series/category/tag) | 0/0/0 phantoms | Clean |

## DLQ analysis (2026-08-07)

All 20 DLQ messages were enqueued on 2026-08-03 during initial ingest
bring-up. Two failure modes visible in the sample:

1. **`post_type: "page"` events** (2 seen) — mu-plugin v0.4 payload
   before v0.6 was deployed to dev. v0.6 filters to `post_type=post`
   per CMS-policy assumption 2. This is now filtered at source.

2. **`post_type: "post"` events with retry-exhausted errors** (1 seen —
   `gileads-trodelvy-...`) — likely a transient error during initial
   hydration when the DB was warming. That specific post is now healthy
   in the mirror (visible in reconcile).

**Action:** drain DLQ before prod cutover (one-shot, low-risk since none
of the messages represent live drift — reconcile has closed to 0 across
all axes).

## Gap-fill proof (WPR-1 reference)

The "known-broken-state reconcile" scenario the ticket asks for was
already proven on 2026-07-28 via WPR-1 (SCRUM-152): 9 real phantom
`wordpress_events` rows on prod were closed via signed synthetic delete
webhooks emitted by the reconcile job. That IS the gap-fill test —
against 9 real phantoms — and it worked cleanly. Since then, dev has
stayed at 0 phantoms across 4 dimensions through 12 active edit days.

## WordPress outage simulation

Not performed. Requires coordinated test window with Andrew (firewall
webhook receiver from WP's outbound IP for ~30 min, then unblock and
observe mu-plugin retry). Deferred to a coordinated slot.

## Ongoing monitoring plan

Run `wpr14_burnin_health.py` daily until 2026-08-10. Any of:
- DLQ delta > 0 vs previous day
- Lambda error count > 0
- Reconcile phantom count > 0

... pauses the WPR-16 prod cutover for investigation.
