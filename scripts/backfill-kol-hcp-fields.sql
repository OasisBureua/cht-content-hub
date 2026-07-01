-- Backfill kols specialty/institution from linked hcps (post KOL+HCP migration).
-- Safe to re-run: only fills NULL/empty kols columns.

UPDATE kols k
SET
  specialty = COALESCE(NULLIF(k.specialty, ''), h.taxonomy),
  institution = COALESCE(NULLIF(k.institution, ''), h.hospital_affiliations),
  title = COALESCE(NULLIF(k.title, ''), NULLIF(h.credential, ''))
FROM hcps h
WHERE k.hcp_npi = h.npi
  AND k.hcp_npi IS NOT NULL;
