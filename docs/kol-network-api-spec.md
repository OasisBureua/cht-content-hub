# KOL Network — Content Hub Public API Spec

**Version:** Content Hub API v0.0.3+  
**Scope:** KOL directory only (not catalog / playlists)  
**Audience:** CHT platform implementation (`cht-platform-tool`)

---

## Base URLs

| Env | Base URL |
|-----|----------|
| Dev | `https://devhub.communityhealth.media/api/public` |
| Prod (future) | `https://contenthub.communityhealth.media/api/public` |

---

## Authentication

All routes require a server-side API key (never expose to the browser).

```http
X-API-Key: <PUBLIC_API_KEY>
Content-Type: application/json
```

| Status | Meaning |
|--------|---------|
| 401 | Missing or invalid X-API-Key |
| 404 | KOL slug not found (detail route) |
| 422 | Validation error (upsert body, query params) |
| 429 | Rate limit (100 requests/minute per route) |

**Error response shape (all /api/public/* errors)**

```json
{
  "errors": {
    "status_code": 401,
    "details": "Missing API key"
  }
}
```

HTTP status on the response matches `errors.status_code`. CHT should read `errors.details` for the message.

---

## CHT integration pattern

```text
Browser  ->  CHT backend  /api/kol-network/*
                |
                +-- server-to-server -->  Content Hub  /api/public/kols/*
                   X-API-Key (KOL_BASE_URL — separate from catalog URL)
```

CHT should add **KOL_BASE_URL** pointing at Content Hub while **MEDIAHUB_BASE_URL** stays on EC2 for catalog until playlisting moves to Content Hub.

---

## Endpoints

### 1. List KOL directory

```http
GET /kols
```

**Query parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| region | string | — | Filter by region slug |
| institution | string | — | Exact institution match |
| q | string | — | Search name, institution, specialty, bio (max 200 chars) |
| new_only | boolean | false | Only KOLs with is_new=true |
| limit | int | 200 | Page size (1–500) |
| offset | int | 0 | Pagination offset |

**Response:** PublicKolList

**Notes**

- `total` is count after filters (new_only, etc.), before pagination slice.
- `regions` and `institutions` are facets from the filtered set.
- `intel` is present when the KOL has a linked hcp_npi.

**Example response (abbreviated)**

```json
{
  "items": [{
    "id": "969c7db9-85e2-4680-ba9a-27d237552fce",
    "slug": "bardia",
    "name": "Dr. Aditya Bardia",
    "title": null,
    "specialty": "Hematology & Oncology",
    "institution": "University Of California Los Angeles David Geffen School Of Medicine",
    "bio": "...",
    "photo_url": "https://contenthub-dev-assets-....amazonaws.com/kol-headshots/aditya-bardia.png",
    "region": "california",
    "region_label": "California",
    "shoot_count": 2,
    "first_appeared_at": "2026-01-24T05:24:26.544074Z",
    "is_new": false,
    "intel": {
      "npi": "1639210107",
      "specialty": "Hematology & Oncology",
      "location": "Los Angeles, CA",
      "email": "abardia1@partners.org",
      "affiliation": "University Of California Los Angeles David Geffen School Of Medicine",
      "publications_approx": 17,
      "open_payments": null,
      "ai_brief": null
    }
  }],
  "total": 39,
  "regions": [{ "slug": "california", "label": "California", "kol_count": 5 }],
  "institutions": ["Dana-Farber Cancer Institute"]
}
```

---

### 2. KOL profile detail

```http
GET /kols/{slug}
```

**Response:** PublicKol (same shape as list item)

**Errors:** 404 `{ "detail": "KOL not found" }`

---

### 3. KOL publications

```http
GET /kols/{slug}/publications
```

**Query parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| limit | int | 20 | 1–100 |
| offset | int | 0 | Pagination |

**Response:** PublicKolPublicationList

**Notes**

- Returns `{ "items": [], "total": 0 }` if KOL has no linked NPI or no publication signals (not an error).
- Data from hcp_signals where signal_type = "publication".

**Example**

```json
{
  "items": [{
    "title": "Abstract C040: Sustained lymphopenia during neoadjuvant chemo-immunotherapy...",
    "url": "https://doi.org/10.1158/2326-6074.io2026-c040",
    "journal": "Cancer Immunology Research",
    "published_at": "2026-02-18T00:00:00Z",
    "is_first_author": false,
    "is_last_author": true
  }],
  "total": 17
}
```

---

### 4. HCP upsert (registration sync)

Same base URL; not used by KOL UI but part of the KOL/HCP ecosystem.

```http
POST /hcp/upsert
```

**Request body (snake_case)**

```json
{
  "npi": "1234567890",
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane@example.com",
  "specialty": "Medical Oncology",
  "city": "Boston",
  "state": "MA",
  "zip": "02115",
  "institution": "Dana-Farber Cancer Institute",
  "source": "cht"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| npi | yes | 10 digits |
| first_name, last_name | yes | |
| email, specialty, city, state, zip, institution | no | specialty -> hcps.taxonomy; institution -> hcps.hospital_affiliations |
| source | no | default "cht" |

**Response:** `{ "created": true, "npi": "1234567890" }`

CHT caller: mediahub-sync.service.ts — only reads `created`.

---

## TypeScript types (CHT)

Update existing types to include **intel** (new vs legacy MediaHub).

```typescript
export interface PublicKolIntel {
  npi?: string | null;
  specialty?: string | null;
  location?: string | null;
  email?: string | null;
  affiliation?: string | null;
  publications_approx?: number | null;
  open_payments?: { total: number; records: number; years: string } | null;
  ai_brief?: { whoTheyAre?: string } | null;
}

export interface PublicKol {
  id: string;
  slug: string;
  name: string;
  title: string | null;
  specialty: string | null;
  institution: string | null;
  bio: string | null;
  photo_url: string | null;
  region: string | null;
  region_label: string | null;
  shoot_count: number;
  first_appeared_at: string | null;
  is_new: boolean;
  intel?: PublicKolIntel | null;
}

export interface PublicKolRegionFacet {
  slug: string;
  label: string;
  kol_count: number;
}

export interface PublicKolList {
  items: PublicKol[];
  total: number;
  regions: PublicKolRegionFacet[];
  institutions: string[];
}

export interface PublicKolPublication {
  title: string;
  url: string | null;
  journal: string | null;
  published_at: string;
  is_first_author: boolean;
  is_last_author: boolean;
}

export interface PublicKolPublicationList {
  items: PublicKolPublication[];
  total: number;
}
```

---

## Field semantics

| Field | Source | CHT usage |
|-------|--------|-----------|
| slug | Derived from last name (+ suffix if collision) | URL /kol-network/{slug} |
| photo_url | S3 CDN URL or null | Card avatar |
| shoot_count | Distinct shoots via KOL group membership | Videos count |
| first_appeared_at | min(shoot.shoot_date, shoot.created_at) | New badge timing |
| is_new | first_appeared_at within 60 days | Filter new_only=true |
| region / region_label | CMS taxonomy | Region filter chips |
| intel | HCP Intel via kols.hcp_npi | Replace dol-network.ts mock |

### Not on API yet (keep static or omit)

| dol-network.ts field | Status |
|----------------------|--------|
| education | Not in API |
| role | Use title or static |
| linkedInUrl, twitterUrl, webUrl | Not in API |
| intel.aiBrief.focus, chmContext | Only whoTheyAre when present |

---

## Region taxonomy

Filter with `?region=<slug>`.

| slug | label |
|------|-------|
| ny-northeast | New York & Northeast |
| new-england | New England |
| east-coast | East Coast Academic Centers |
| florida | Florida |
| midwest-chicago | Midwest — Chicago |
| midwest-indiana | Midwest — Indiana |
| missouri | Missouri |
| kansas | Kansas |
| tennessee | Tennessee |
| texas | Texas |
| colorado | Colorado |
| pacific-northwest | Pacific Northwest |
| california | California |

---

## Slug rules

1. Strip leading Dr. / Dr
2. Take portion before first comma
3. Use last word of name, lowercase alphanumeric + hyphens
4. Collisions: append -2, -3, ... (sorted by name)

Examples: Dr. Aditya Bardia -> bardia; duplicate last names -> smith-2.

---

## CHT backend proxy

| CHT route | Proxies to |
|-----------|------------|
| GET /api/kol-network | GET {KOL_BASE_URL}/kols |
| GET /api/kol-network/:slug | GET {KOL_BASE_URL}/kols/:slug |
| GET /api/kol-network/:slug/publications | GET {KOL_BASE_URL}/kols/:slug/publications |

**Degradation (keep current behavior)**

- List failure -> empty list payload
- Detail failure -> 404
- Publications failure -> empty items

---

## Environment variables (CHT)

```bash
KOL_BASE_URL=https://devhub.communityhealth.media/api/public
KOL_API_KEY=<contenthub public_api_key>

MEDIAHUB_BASE_URL=https://mediahub.communityhealth.media/api/public
MEDIAHUB_API_KEY=...
```

Catalog stays on MEDIAHUB_BASE_URL until playlist migration.

---

## Smoke test

```bash
KEY=<public_api_key>
BASE=https://devhub.communityhealth.media/api/public

curl -s -H "X-API-Key: $KEY" "$BASE/kols?limit=1"
curl -s -H "X-API-Key: $KEY" "$BASE/kols/bardia"
curl -s -H "X-API-Key: $KEY" "$BASE/kols/bardia/publications?limit=1"
```

---

## Implementation checklist

- [ ] Add KOL_BASE_URL + dedicated HTTP client in KolNetworkModule
- [ ] Extend PublicKol / MediaHubKol with optional intel
- [ ] Prefer apiKol.intel over dol-network.ts for NPI, open payments, publications count, AI brief
- [ ] Keep dol-network.ts only for education, social URLs until API adds them
- [ ] Point registration upsert at /hcp/upsert when ready

**Canonical source:** backend/src/schemas/public.py, backend/src/public/router.py
