"""Public API schemas — KOL network (Step 3)."""

from datetime import datetime

from pydantic import BaseModel


class PublicKOLAIBrief(BaseModel):
    """Three-section HCP AI brief consumed by the CHT KOL profile Background tab.

    MediaHub's brief generator emits a single markdown blob with three fixed
    `## Who they are / ## What they focus on / ## CHM context` headings. The
    producer parses that markdown into these three fields so the frontend can
    render each section under its own label instead of dumping the raw markdown
    into a single paragraph.
    """

    whoTheyAre: str | None = None
    focus: str | None = None
    chmContext: str | None = None


class PublicKOLIntel(BaseModel):
    """Optional HCP Intel overlay — mirrors CHT KolIntel subset for /kol-network."""

    npi: str | None = None
    specialty: str | None = None
    location: str | None = None
    email: str | None = None
    affiliation: str | None = None
    publications_approx: int | None = None
    open_payments: dict | None = None
    ai_brief: PublicKOLAIBrief | None = None


class PublicKOL(BaseModel):
    id: str
    slug: str
    name: str
    title: str | None
    specialty: str | None
    institution: str | None
    bio: str | None
    photo_url: str | None
    region: str | None
    region_label: str | None
    shoot_count: int
    first_appeared_at: datetime | None
    is_new: bool
    intel: PublicKOLIntel | None = None


class PublicKOLRegion(BaseModel):
    slug: str
    label: str
    kol_count: int


class PublicKOLList(BaseModel):
    items: list[PublicKOL]
    total: int
    regions: list[PublicKOLRegion]
    institutions: list[str]


class PublicKOLPublication(BaseModel):
    title: str
    url: str | None
    journal: str | None
    published_at: datetime
    is_first_author: bool = False
    is_last_author: bool = False


class PublicKOLPublicationList(BaseModel):
    items: list[PublicKOLPublication]
    total: int


class PublicPlaylistTag(BaseModel):
    """Curator-set tag overlay for a YouTube playlist.

    Returned by /api/public/playlists. The full playlist metadata (title,
    description, videos) lives in YouTube — fetch that separately via the
    YouTube Data API. This row is purely the editorial overlay: "this
    playlist is intended to be a biomarker:HER2+ playlist."

    CHT uses this to render biomarker rows by querying the playlist_tags
    table instead of the brittle frontend JSON file that fuzzy-matched
    playlist titles. CHT joins these tags with YouTube's actual playlist
    metadata client-side.
    """

    youtube_playlist_id: str
    tags: list[str]
    lane: str | None


class PublicPlaylistTagList(BaseModel):
    items: list[PublicPlaylistTag]
    total: int


class HCPUpsertRequest(BaseModel):
    """CHT registration sync — snake_case body matches mediahub-sync.service.ts."""

    npi: str
    first_name: str
    last_name: str
    email: str | None = None
    specialty: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    institution: str | None = None
    source: str = "cht"


class HCPUpsertResponse(BaseModel):
    created: bool
    npi: str


class PublicWordPressCategory(BaseModel):
    """WordPress category slug + count of posts currently on it.

    Pass-through from `wordpress_events`. Slugs are open-vocabulary
    (Andrew's editorial team owns the taxonomy in wp-admin).
    """

    slug: str
    post_count: int


class PublicWordPressCategoryList(BaseModel):
    items: list[PublicWordPressCategory]
    total: int


class PublicWordPressPost(BaseModel):
    """Current editorial state of one WordPress post.

    Latest non-deleted event per `post_id`. Deleted posts are excluded.
    All fields are verbatim from WordPress — no ContentHub-side
    tagging or curation is applied.
    """

    post_id: int
    slug: str
    title: str
    permalink: str
    categories: list[str]
    tags: list[str]
    youtube_video_id: str | None
    featured_media_url: str | None
    modified_gmt: datetime


class PublicWordPressPostList(BaseModel):
    items: list[PublicWordPressPost]
    total: int


class PublicClip(BaseModel):
    """Public-facing clip w/ engagement stats. Contract mirrors mediahub /api/public/clips exactly."""

    id: str
    title: str | None
    description: str | None
    ai_summary: str | None = None
    tags: list[str]
    doctors: list[str]
    thumbnail_url: str | None
    youtube_url: str | None
    duration_seconds: int | None
    is_short: bool | None
    posted_at: datetime | None
    view_count: int
    like_count: int
    comment_count: int
    shoot_id: str | None
    shoot_name: str | None


class PublicDoctor(BaseModel):
    """Doctor entry for VideosPage filter dropdown. Frontend reads slug only —
    mediahub also emitted shoot_count / post_count / total_views / total_likes,
    none of which the frontend consumes. Kept minimal."""

    slug: str


class PublicTranscript(BaseModel):
    """Diarized shoot transcript. Frontend reads `transcript` (string, split on
    newlines into paragraphs) and `shoot_name` only. Mediahub also emitted
    shoot_id / doctors / length; none consumed."""

    transcript: str
    shoot_name: str | None
