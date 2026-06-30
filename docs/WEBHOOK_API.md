# MediaHub Webhook API Contract

This document defines the webhook API that MediaHub exposes for receiving data from external systems.

## Overview

MediaHub receives clip, post, and shoot data via a webhook endpoint. This allows any authorized system to push analytics and content data into the portal.

**Key principle**: MediaHub works independently. The webhook is for receiving updates, not a required dependency.

---

## Authentication

All webhook requests require an API key in the header:

```
X-API-Key: <your-api-key>
```

API keys are configured in MediaHub's environment variables.

---

## Endpoints

### POST /webhook/sync

Sync clips, posts, and shoots to MediaHub.

**Request:**

```http
POST /webhook/sync
Content-Type: application/json
X-API-Key: <api-key>
```

**Request Body:**

```json
{
  "clips": [...],
  "posts": [...],
  "shoots": [...]
}
```

**Response:**

```json
{
  "success": true,
  "clips_synced": 10,
  "posts_synced": 25,
  "shoots_synced": 5,
  "errors": []
}
```

---

## Data Schemas

### Clip Object

```json
{
  "id": "string (required)",
  "title": "string | null",
  "description": "string | null",
  "platform": "youtube | linkedin | x | null",
  "status": "draft | ready | scheduled | published",
  "tags": ["string"],
  "aspect": "16:9 | 9:16 | 1:1 | null",
  "privacy": "public | private | unlisted | null",
  "video_path": "string | null",
  "shoot_id": "uuid | null",
  "raw": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique clip identifier |
| `title` | string | No | Clip title |
| `description` | string | No | Clip description |
| `platform` | enum | No | Target platform |
| `status` | enum | No | Current status (default: draft) |
| `tags` | array | No | Content tags |
| `aspect` | string | No | Video aspect ratio |
| `privacy` | string | No | Privacy setting |
| `video_path` | string | No | Path to video file |
| `shoot_id` | uuid | No | Associated shoot |
| `raw` | object | No | Raw metadata from source |

### Post Object

```json
{
  "id": "uuid (required)",
  "clip_id": "string | null",
  "shoot_id": "uuid | null",
  "platform": "string (required)",
  "provider_post_id": "string (required)",
  "title": "string | null",
  "description": "string | null",
  "posted_at": "ISO8601 | null",
  "view_count": 0,
  "like_count": 0,
  "comment_count": 0,
  "share_count": 0,
  "impression_count": 0,
  "stats_synced_at": "ISO8601 | null"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | uuid | Yes | Unique post identifier |
| `clip_id` | string | No | Source clip ID |
| `shoot_id` | uuid | No | Associated shoot |
| `platform` | string | Yes | Platform name (youtube, linkedin, x) |
| `provider_post_id` | string | Yes | Platform's post ID |
| `title` | string | No | Post title |
| `description` | string | No | Post description/caption |
| `posted_at` | datetime | No | When posted (ISO8601) |
| `view_count` | int | No | Number of views |
| `like_count` | int | No | Number of likes |
| `comment_count` | int | No | Number of comments |
| `share_count` | int | No | Number of shares |
| `impression_count` | int | No | Number of impressions |
| `stats_synced_at` | datetime | No | When stats were last updated |

### Shoot Object

```json
{
  "id": "uuid (required)",
  "name": "string (required)",
  "doctors": ["string"],
  "shoot_date": "ISO8601 | null",
  "diarized_transcript": "string | null"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | uuid | Yes | Unique shoot identifier |
| `name` | string | Yes | Shoot name (e.g., "Podcast 20") |
| `doctors` | array | No | List of doctor names |
| `shoot_date` | datetime | No | Date of recording |
| `diarized_transcript` | string | No | Speaker-labeled transcript |

---

## Error Handling

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid JSON, missing fields) |
| 401 | Unauthorized (missing or invalid API key) |
| 422 | Validation error (schema mismatch) |
| 500 | Server error |

### Error Response Format

```json
{
  "success": false,
  "error": "Error message",
  "details": {}
}
```

---

## Sync Behavior

### Upsert Logic

The webhook performs **upserts** based on primary keys:
- Clips: upserted by `id`
- Posts: upserted by `platform` + `provider_post_id`
- Shoots: upserted by `id`

Existing records are updated; new records are created.

### Partial Sync

You can sync any subset of data:

```json
{
  "clips": [],
  "posts": [...],
  "shoots": []
}
```

Empty arrays are valid and skip that entity type.

---

## Example: Full Sync Request

```bash
curl -X POST https://mediahub.example.com/webhook/sync \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "clips": [
      {
        "id": "youtube:abc123",
        "title": "Dr. Smith on Heart Health",
        "platform": "youtube",
        "status": "published",
        "shoot_id": "550e8400-e29b-41d4-a716-446655440000"
      }
    ],
    "posts": [
      {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "clip_id": "youtube:abc123",
        "platform": "youtube",
        "provider_post_id": "dQw4w9WgXcQ",
        "title": "Dr. Smith on Heart Health",
        "posted_at": "2026-01-15T10:30:00Z",
        "view_count": 1523,
        "like_count": 87
      }
    ],
    "shoots": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "Podcast 20",
        "doctors": ["Dr. Smith", "Dr. Jones"],
        "shoot_date": "2026-01-10T09:00:00Z"
      }
    ]
  }'
```

---

## Development / Testing

For local development without an external data source, use the seed data script:

```bash
python scripts/seed_data.py
```

This populates MediaHub with sample data for testing.
