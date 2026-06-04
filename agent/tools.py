"""
Tool implementations called by the agent loop.
Each function talks directly to an external API and returns a plain dict.
"""

from __future__ import annotations
import os
import re
import json
import time
import unicodedata
import requests
from typing import Any

from . import config as cfg


# ── helpers ──────────────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    key = os.environ["NOTION_API_KEY"]
    return {"Authorization": f"Bearer {key}", "Notion-Version": cfg.NOTION_VERSION,
            "Content-Type": "application/json"}


def _webflow_headers() -> dict:
    key = os.environ["WEBFLOW_API_KEY"]
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def _raise_for(resp: requests.Response) -> None:
    if not resp.ok:
        msg = resp.text[:400]
        if resp.status_code == 404 and "object_not_found" in msg:
            raise RuntimeError(
                f"HTTP 404 – database not found. Make sure you have shared this database "
                f"with your Notion integration ('Contortion Space Agent'). Full error: {msg}"
            )
        raise RuntimeError(f"HTTP {resp.status_code}: {msg}")


def _notion_append_blocks(page_id: str, blocks: list[dict]) -> None:
    """Append blocks to an existing Notion page, chunking to respect the 100-block limit."""
    for i in range(0, len(blocks), 100):
        chunk = blocks[i:i + 100]
        resp = requests.patch(
            f"{cfg.NOTION_BASE}/blocks/{page_id}/children",
            headers=_notion_headers(),
            json={"children": chunk},
            timeout=30,
        )
        _raise_for(resp)


# ── web search ───────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 8) -> dict:
    """
    Search the web using Tavily.  Falls back to a Serper.dev call if
    TAVILY_API_KEY is not set but SERPER_API_KEY is.
    """
    tavily_key = os.environ.get("TAVILY_API_KEY")
    serper_key = os.environ.get("SERPER_API_KEY")

    if tavily_key:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": tavily_key, "query": query,
                  "max_results": max_results, "search_depth": "advanced"},
            timeout=30,
        )
        _raise_for(resp)
        data = resp.json()
        results = [
            {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content", "")[:400]}
            for r in data.get("results", [])
        ]
        return {"results": results}

    if serper_key:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
            timeout=30,
        )
        _raise_for(resp)
        data = resp.json()
        results = [
            {"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet", "")}
            for r in data.get("organic", [])
        ]
        return {"results": results}

    raise RuntimeError(
        "No search API key found. Set TAVILY_API_KEY or SERPER_API_KEY."
    )


# ── Notion ───────────────────────────────────────────────────────────────────

def notion_create_research_page(month_label: str, content_markdown: str) -> dict:
    """Create a research-notes page in the Monthly research Notion database."""
    blocks = _markdown_to_notion_blocks(content_markdown)
    # Notion allows at most 100 blocks on page creation; append the rest after
    payload = {
        "parent": {"database_id": cfg.get("NOTION_MONTHLY_RESEARCH_DS")},
        "properties": {
            "Research month": {"title": [{"text": {"content": month_label}}]},
        },
        "children": blocks[:100],
    }
    resp = requests.post(f"{cfg.NOTION_BASE}/pages", headers=_notion_headers(), json=payload, timeout=30)
    _raise_for(resp)
    page = resp.json()
    if len(blocks) > 100:
        _notion_append_blocks(page["id"], blocks[100:])
    return {"page_id": page["id"], "url": page["url"]}


def notion_create_article_page(
    month_label: str,
    article_body: str,
    performer_page_ids: list[str],
    show_page_ids: list[str] | None = None,
) -> dict:
    """
    Create the monthly article in the Monthly performance posts Notion database,
    linking the relevant performer and show pages.
    """
    properties: dict = {
        "Name": {"title": [{"text": {"content": month_label}}]},
        "Performers mentioned": {
            "relation": [{"id": pid} for pid in performer_page_ids]
        },
    }
    if show_page_ids:
        properties["Shows"] = {"relation": [{"id": sid} for sid in show_page_ids]}

    blocks = _markdown_to_notion_blocks(article_body)
    payload = {
        "parent": {"database_id": cfg.get("NOTION_MONTHLY_POSTS_DS")},
        "properties": properties,
        "children": blocks[:100],
    }
    resp = requests.post(f"{cfg.NOTION_BASE}/pages", headers=_notion_headers(), json=payload, timeout=30)
    _raise_for(resp)
    page = resp.json()
    if len(blocks) > 100:
        _notion_append_blocks(page["id"], blocks[100:])
    return {"page_id": page["id"], "url": page["url"]}


def notion_search_performer(name: str) -> dict:
    """Search the ICPDB for a performer by name."""
    resp = requests.post(
        f"{cfg.NOTION_BASE}/search",
        headers=_notion_headers(),
        json={"query": name, "filter": {"value": "page", "property": "object"}},
        timeout=30,
    )
    _raise_for(resp)
    results = resp.json().get("results", [])
    matches = []
    for page in results:
        props = page.get("properties", {})
        title_prop = props.get("Contortionist name", {})
        title_texts = title_prop.get("title", [])
        if not title_texts:
            continue
        page_name = title_texts[0].get("plain_text", "")
        if name.lower() not in page_name.lower():
            continue
        instagram_prop = props.get("Instagram", {})
        instagram = instagram_prop.get("rich_text", [{}])
        instagram_handle = instagram[0].get("plain_text", "") if instagram else ""
        matches.append({
            "id": page["id"],
            "name": page_name,
            "instagram": instagram_handle,
            "url": page.get("url", ""),
        })
    return {"matches": matches}


def notion_list_performers_in_icpdb(limit: int = 200) -> dict:
    """Returns all performers in the ICPDB (up to `limit`) with id, name, instagram."""
    all_results = []
    has_more = True
    cursor = None
    while has_more and len(all_results) < limit:
        payload: dict[str, Any] = {
            "filter": {"property": "Performer status", "select": {"equals": "Performing"}},
            "page_size": min(100, limit - len(all_results)),
        }
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(
            f"{cfg.NOTION_BASE}/databases/{cfg.get('NOTION_ICPDB_DS')}/query",
            headers=_notion_headers(),
            json=payload,
            timeout=30,
        )
        _raise_for(resp)
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            name_texts = props.get("Contortionist name", {}).get("title", [])
            name = name_texts[0].get("plain_text", "") if name_texts else ""
            ig_texts = props.get("Instagram", {}).get("rich_text", [])
            instagram = ig_texts[0].get("plain_text", "") if ig_texts else ""
            all_results.append({"id": page["id"], "name": name, "instagram": instagram, "url": page.get("url", "")})
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")
    return {"performers": all_results}


def notion_create_performer(name: str, instagram: str = "") -> dict:
    """Create a new performer page in the ICPDB."""
    properties: dict = {
        "Contortionist name": {"title": [{"text": {"content": name}}]},
        "Performer status": {"select": {"name": "Performing"}},
    }
    if instagram:
        properties["Instagram"] = {"rich_text": [{"text": {"content": instagram}}]}

    payload = {
        "parent": {"database_id": cfg.get("NOTION_ICPDB_DS")},
        "properties": properties,
    }
    resp = requests.post(f"{cfg.NOTION_BASE}/pages", headers=_notion_headers(), json=payload, timeout=30)
    _raise_for(resp)
    page = resp.json()
    return {"page_id": page["id"], "url": page["url"], "name": name}


def notion_list_shows(limit: int = 200) -> dict:
    """Returns shows from the Shows database for linking to the article."""
    all_results: list[dict] = []
    has_more = True
    cursor = None
    while has_more and len(all_results) < limit:
        payload: dict[str, Any] = {
            "page_size": min(100, limit - len(all_results)),
        }
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(
            f"{cfg.NOTION_BASE}/databases/{cfg.get('NOTION_SHOWS_DS')}/query",
            headers=_notion_headers(),
            json=payload,
            timeout=30,
        )
        _raise_for(resp)
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            name = ""
            for key in ("Name", "Show name", "Title"):
                name_texts = props.get(key, {}).get("title", [])
                if name_texts:
                    name = name_texts[0].get("plain_text", "")
                    break
            all_results.append({"id": page["id"], "name": name, "url": page.get("url", "")})
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")
    return {"shows": all_results}


def notion_search_show(name: str) -> dict:
    """Search the Shows database for a specific show by name."""
    resp = requests.post(
        f"{cfg.NOTION_BASE}/search",
        headers=_notion_headers(),
        json={"query": name, "filter": {"value": "page", "property": "object"}},
        timeout=30,
    )
    _raise_for(resp)
    results = resp.json().get("results", [])
    matches = []
    shows_id = cfg.get("NOTION_SHOWS_DS").replace("-", "")
    for page in results:
        parent = page.get("parent", {})
        db_id = parent.get("database_id", "").replace("-", "")
        if db_id != shows_id:
            continue
        props = page.get("properties", {})
        page_name = ""
        for key in ("Name", "Show name", "Title"):
            name_texts = props.get(key, {}).get("title", [])
            if name_texts:
                page_name = name_texts[0].get("plain_text", "")
                break
        if name.lower() in page_name.lower():
            matches.append({"id": page["id"], "name": page_name, "url": page.get("url", "")})
    return {"matches": matches}


# ── Webflow ───────────────────────────────────────────────────────────────────

def webflow_find_performers(names: list[str]) -> dict:
    """Look up Webflow Contortion Performers by name and return their item IDs."""
    resp = requests.get(
        f"{cfg.WEBFLOW_BASE}/collections/{cfg.WEBFLOW_PERF_COL_ID}/items",
        headers=_webflow_headers(),
        params={"limit": 100},
        timeout=30,
    )
    _raise_for(resp)
    items = resp.json().get("items", [])
    found = []
    names_lower = [n.lower() for n in names]
    for item in items:
        item_name = item.get("fieldData", {}).get("performer-name", "") or item.get("fieldData", {}).get("name", "")
        if any(nl in item_name.lower() or item_name.lower() in nl for nl in names_lower):
            found.append({"id": item["id"], "name": item_name})
    return {"found": found}


def webflow_create_blog_draft(
    title: str,
    slug: str,
    description: str,
    body_html: str,
    featured_performer_ids: list[str] | None = None,
    hero_image_asset_id: str | None = None,
) -> dict:
    """Create a draft Blog Post item in Webflow CMS."""
    field_data: dict[str, Any] = {
        cfg.WF_FIELD_NAME: title,
        cfg.WF_FIELD_SLUG: slug,
        cfg.WF_FIELD_POST_BODY: body_html,
        cfg.WF_FIELD_POST_DESC: description,
        cfg.WF_FIELD_POST_TYPE2: cfg.WF_POST_TYPE_ARTICLE,
        cfg.WF_FIELD_MONTHLY_ROUNDUP: True,
    }
    if featured_performer_ids:
        field_data[cfg.WF_FIELD_FEAT_PERFORMERS] = featured_performer_ids
    if hero_image_asset_id:
        field_data["hero-image"] = {"assetId": hero_image_asset_id}

    payload = {"fieldData": field_data, "isDraft": True}
    resp = requests.post(
        f"{cfg.WEBFLOW_BASE}/collections/{cfg.WEBFLOW_BLOG_COL_ID}/items",
        headers=_webflow_headers(),
        json=payload,
        timeout=30,
    )
    _raise_for(resp)
    item = resp.json()
    item_id = item.get("id", "")
    preview_url = f"https://contortion.space/blog/{slug}"
    return {"item_id": item_id, "draft_url": preview_url,
            "webflow_editor_url": f"https://webflow.com/design/{cfg.WEBFLOW_SITE_ID}"}


# ── Notion markdown → blocks (lightweight) ───────────────────────────────────

def _markdown_to_notion_blocks(md: str) -> list[dict]:
    blocks = []
    for line in md.split("\n"):
        stripped = line.rstrip()
        if stripped.startswith("### "):
            blocks.append(_heading(3, stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(_heading(2, stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(_heading(1, stripped[2:]))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_bullet(stripped[2:]))
        elif stripped == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif stripped == "":
            pass
        else:
            blocks.append(_paragraph(stripped))
    return blocks


def _rich_text(text: str) -> list[dict]:
    """Parse inline markdown (bold, italic, links) into Notion rich_text objects."""
    parts = []
    pattern = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|\[(.+?)\]\((.+?)\)|(.+?)(?=\*\*|\*|\[|$)", re.DOTALL)
    for m in pattern.finditer(text):
        if not any(m.groups()):
            continue
        bold_text, italic_text, link_text, link_url, plain = m.groups()
        if bold_text:
            parts.append({"type": "text", "text": {"content": bold_text}, "annotations": {"bold": True}})
        elif italic_text:
            parts.append({"type": "text", "text": {"content": italic_text}, "annotations": {"italic": True}})
        elif link_text and link_url:
            parts.append({"type": "text", "text": {"content": link_text, "link": {"url": link_url}}})
        elif plain:
            parts.append({"type": "text", "text": {"content": plain}})
    return parts or [{"type": "text", "text": {"content": text}}]


# ── Image generation ──────────────────────────────────────────────────────────

def generate_images(month_label: str, performer_page_ids: list[str]) -> dict:
    from .compositor import generate_and_upload_images
    return generate_and_upload_images(month_label, performer_page_ids)


def _heading(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rich_text(text)}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rich_text(text)}}
