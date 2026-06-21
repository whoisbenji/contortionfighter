"""
Hardcoded IDs for the Contortion Space Notion + Webflow integrations.
All IDs were read directly from the live workspace / site.
"""

# ── Claude ───────────────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

# ── Notion ──────────────────────────────────────────────────────────────────
NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

# Collection (data-source) IDs
NOTION_MONTHLY_POSTS_DS    = "23e3c48a-f297-806a-b2ed-000b34c63f74"   # Monthly performance posts
NOTION_MONTHLY_RESEARCH_DS = "3293c48a-f297-8010-b5fc-000b5f289537"  # Monthly research
NOTION_ICPDB_DS            = "3253c48a-f297-8053-899f-d014af1786ab"   # ICPDB performers
NOTION_SHOWS_DS            = "3253c48a-f297-805e-9f63-e7672d0ecb35"   # Shows
NOTION_JOBS_DS             = ""   # Circus Jobs — set via admin panel or NOTION_JOBS_DS env var

# ── Webflow ──────────────────────────────────────────────────────────────────
WEBFLOW_BASE = "https://api.webflow.com/v2"
WEBFLOW_SITE_ID        = "618aa3d4f4125125a941015a"
WEBFLOW_BLOG_COL_ID    = "618aa3d4f41251e44f41016d"   # Blog Posts
WEBFLOW_PERF_COL_ID    = "69373df714a3d63090fa4490"   # Contortion Performers

# Webflow Blog Posts field IDs (used when creating CMS items)
WF_FIELD_NAME            = "name"
WF_FIELD_SLUG            = "slug"
WF_FIELD_POST_BODY       = "post-body"
WF_FIELD_POST_DESC       = "post-decription"          # note: typo is in Webflow schema
WF_FIELD_POST_TYPE2      = "post-type-2"
WF_FIELD_MONTHLY_ROUNDUP = "monthly-roundup"
WF_FIELD_FEAT_PERFORMERS = "featured-performers"

# Webflow Blog Post type option IDs
WF_POST_TYPE_ARTICLE     = "9d81099cc178be8bc8adfce88dcb71d2"

# ── Runtime overrides (set via admin panel) ───────────────────────────────────
_overrides: dict = {}

_DEFAULTS = {
    "NOTION_MONTHLY_POSTS_DS":    NOTION_MONTHLY_POSTS_DS,
    "NOTION_MONTHLY_RESEARCH_DS": NOTION_MONTHLY_RESEARCH_DS,
    "NOTION_ICPDB_DS":            NOTION_ICPDB_DS,
    "NOTION_SHOWS_DS":            NOTION_SHOWS_DS,
    "NOTION_JOBS_DS":             NOTION_JOBS_DS,
}


def set_overrides(d: dict) -> None:
    """Apply admin-panel DB ID overrides for the current session."""
    _overrides.clear()
    _overrides.update({k: v for k, v in d.items() if v})


def get(key: str) -> str:
    """Return override → env var → module default, in that order."""
    import os as _os
    if key in _overrides:
        return _overrides[key]
    env = _os.environ.get(key, "")
    if env:
        return env
    return _DEFAULTS.get(key, globals().get(key, ""))

