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
    db_id = cfg.get("NOTION_MONTHLY_RESEARCH_DS")

    db_resp = requests.get(
        f"{cfg.NOTION_BASE}/databases/{db_id}",
        headers=_notion_headers(),
        timeout=30,
    )
    _raise_for(db_resp)
    db_props = db_resp.json().get("properties", {})
    title_prop_name = next(
        (name for name, p in db_props.items() if p.get("type") == "title"),
        "Name",
    )

    blocks = _markdown_to_notion_blocks(content_markdown)
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            title_prop_name: {"title": [{"text": {"content": month_label}}]},
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
    db_id = cfg.get("NOTION_MONTHLY_POSTS_DS")

    # Fetch the database schema to discover actual property names
    db_resp = requests.get(
        f"{cfg.NOTION_BASE}/databases/{db_id}",
        headers=_notion_headers(),
        timeout=30,
    )
    _raise_for(db_resp)
    db_props = db_resp.json().get("properties", {})

    # Find the title property (there's always exactly one)
    title_prop_name = next(
        (name for name, p in db_props.items() if p.get("type") == "title"),
        "Name",
    )

    # Find relation properties — match by checking which database they point to
    performer_prop_name: str | None = None
    shows_prop_name: str | None = None
    icpdb_id_clean = cfg.get("NOTION_ICPDB_DS").replace("-", "")
    shows_id_clean = cfg.get("NOTION_SHOWS_DS").replace("-", "")
    for name, p in db_props.items():
        if p.get("type") != "relation":
            continue
        related_db = p.get("relation", {}).get("database_id", "").replace("-", "")
        if related_db == icpdb_id_clean:
            performer_prop_name = name
        elif related_db == shows_id_clean:
            shows_prop_name = name

    properties: dict = {
        title_prop_name: {"title": [{"text": {"content": month_label}}]},
    }
    if performer_prop_name and performer_page_ids:
        properties[performer_prop_name] = {
            "relation": [{"id": pid} for pid in performer_page_ids]
        }
    if shows_prop_name and show_page_ids:
        properties[shows_prop_name] = {
            "relation": [{"id": sid} for sid in show_page_ids]
        }

    blocks = _markdown_to_notion_blocks(article_body)
    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
        "children": blocks[:100],
    }
    resp = requests.post(f"{cfg.NOTION_BASE}/pages", headers=_notion_headers(), json=payload, timeout=30)
    _raise_for(resp)
    page = resp.json()
    if len(blocks) > 100:
        _notion_append_blocks(page["id"], blocks[100:])
    return {
        "page_id": page["id"],
        "url": page["url"],
        "title_property": title_prop_name,
        "performer_property": performer_prop_name,
        "shows_property": shows_prop_name,
    }


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


def notion_search_pages(query: str, page_size: int = 10) -> dict:
    """Search all Notion pages/databases the integration can access."""
    resp = requests.post(
        f"{cfg.NOTION_BASE}/search",
        headers=_notion_headers(),
        json={
            "query": query,
            "filter": {"value": "page", "property": "object"},
            "page_size": page_size,
        },
        timeout=30,
    )
    _raise_for(resp)
    results = []
    for page in resp.json().get("results", []):
        props = page.get("properties", {})
        # Try common title property names
        title = ""
        for key in ("title", "Name", "Contortionist name", "Title"):
            prop = props.get(key, {})
            texts = prop.get("title", prop.get("rich_text", []))
            if texts:
                title = texts[0].get("plain_text", "")
                break
        if not title:
            title = page.get("url", page["id"])
        results.append({
            "id": page["id"],
            "title": title,
            "url": page.get("url", ""),
            "last_edited": page.get("last_edited_time", "")[:10],
        })
    return {"results": results}


def _blocks_to_text(blocks: list[dict], indent: int = 0) -> str:
    """Convert Notion block objects to plain readable text."""
    lines = []
    prefix = "  " * indent
    for block in blocks:
        btype = block.get("type", "")
        content = block.get(btype, {})

        # Extract rich text
        rich = content.get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich)

        if btype == "paragraph":
            if text:
                lines.append(prefix + text)
        elif btype in ("heading_1", "heading_2", "heading_3"):
            level = btype[-1]
            lines.append(prefix + "#" * int(level) + " " + text)
        elif btype == "bulleted_list_item":
            lines.append(prefix + "• " + text)
        elif btype == "numbered_list_item":
            lines.append(prefix + "1. " + text)
        elif btype == "to_do":
            done = "✓" if content.get("checked") else "☐"
            lines.append(prefix + f"{done} {text}")
        elif btype == "quote":
            lines.append(prefix + "> " + text)
        elif btype == "callout":
            emoji = (content.get("icon") or {}).get("emoji", "")
            lines.append(prefix + f"{emoji} {text}".strip())
        elif btype == "code":
            lang = content.get("language", "")
            lines.append(prefix + f"```{lang}\n{text}\n```")
        elif btype == "divider":
            lines.append(prefix + "---")
        elif btype == "child_page":
            title = content.get("title", "")
            lines.append(prefix + f"[sub-page: {title}]")

        # Recurse into children if already fetched
        children = block.get("children", [])
        if children:
            lines.append(_blocks_to_text(children, indent + 1))

    return "\n".join(filter(None, lines))


def _fetch_database(db_id: str, max_rows: int = 50) -> dict:
    """Fetch a Notion database — returns its title, schema fields, and up to max_rows rows."""
    # Database metadata
    db_resp = requests.get(
        f"{cfg.NOTION_BASE}/databases/{db_id}",
        headers=_notion_headers(),
        timeout=30,
    )
    _raise_for(db_resp)
    db = db_resp.json()

    # Title
    title_parts = db.get("title", [])
    title = "".join(t.get("plain_text", "") for t in title_parts)

    # Schema fields
    fields = list(db.get("properties", {}).keys())

    # Query rows
    rows_resp = requests.post(
        f"{cfg.NOTION_BASE}/databases/{db_id}/query",
        headers=_notion_headers(),
        json={"page_size": max_rows},
        timeout=30,
    )
    _raise_for(rows_resp)
    rows_data = rows_resp.json().get("results", [])

    rows = []
    for page in rows_data:
        row: dict[str, str] = {"id": page["id"], "url": page.get("url", "")}
        for key, prop in page.get("properties", {}).items():
            ptype = prop.get("type", "")
            if ptype == "title":
                texts = prop.get("title", [])
                row[key] = "".join(t.get("plain_text", "") for t in texts)
            elif ptype == "rich_text":
                texts = prop.get("rich_text", [])
                val = "".join(t.get("plain_text", "") for t in texts)
                if val:
                    row[key] = val
            elif ptype in ("select", "status"):
                sel = prop.get(ptype) or {}
                if sel.get("name"):
                    row[key] = sel["name"]
            elif ptype == "multi_select":
                vals = [s["name"] for s in prop.get("multi_select", []) if s.get("name")]
                if vals:
                    row[key] = ", ".join(vals)
            elif ptype == "date":
                d = prop.get("date") or {}
                if d.get("start"):
                    row[key] = d["start"]
            elif ptype == "checkbox":
                row[key] = "yes" if prop.get("checkbox") else "no"
            elif ptype == "number":
                if prop.get("number") is not None:
                    row[key] = str(prop["number"])
            elif ptype == "url":
                if prop.get("url"):
                    row[key] = prop["url"]
        rows.append(row)

    return {
        "type": "database",
        "title": title,
        "fields": fields,
        "row_count": len(rows),
        "rows": rows,
    }


def notion_fetch_page(page_id_or_url: str, max_blocks: int = 200) -> dict:
    """
    Fetch a Notion page's title, properties and body text.
    Accepts either a page ID or a notion.so URL.
    Returns {title, url, properties, body_text}.
    """
    # Extract and normalise the page ID
    page_id = page_id_or_url.strip()

    # Strip query params / fragments
    page_id = re.split(r'[?#]', page_id)[0].rstrip("/")

    # If it looks like a URL, pull the 32-char hex ID out with a regex
    if "notion.so" in page_id or "/" in page_id:
        # Match a UUID with dashes (standard Notion format)
        m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', page_id)
        if m:
            page_id = m.group(1)
        else:
            # Match 32 bare hex chars at the end of the last path segment
            m = re.search(r'([0-9a-f]{32})(?:[^0-9a-f]|$)', page_id)
            if m:
                raw = m.group(1)
                page_id = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    elif len(page_id) == 32 and re.fullmatch(r'[0-9a-f]{32}', page_id):
        # Bare 32-char hex ID — format as UUID
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    # Fetch — try as page first, fall back to database if Notion says so
    page_resp = requests.get(
        f"{cfg.NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        timeout=30,
    )

    if not page_resp.ok:
        err = page_resp.json()
        if err.get("code") == "validation_error" and "is a database" in err.get("message", ""):
            return _fetch_database(page_id)
        _raise_for(page_resp)

    page = page_resp.json()

    # Extract title from properties
    title = ""
    props_out: dict[str, str] = {}
    for key, prop in page.get("properties", {}).items():
        ptype = prop.get("type", "")
        if ptype == "title":
            texts = prop.get("title", [])
            val = "".join(t.get("plain_text", "") for t in texts)
            title = val
            props_out[key] = val
        elif ptype == "rich_text":
            texts = prop.get("rich_text", [])
            val = "".join(t.get("plain_text", "") for t in texts)
            if val:
                props_out[key] = val
        elif ptype in ("select", "status"):
            sel = prop.get(ptype) or {}
            if sel.get("name"):
                props_out[key] = sel["name"]
        elif ptype == "multi_select":
            vals = [s["name"] for s in prop.get("multi_select", []) if s.get("name")]
            if vals:
                props_out[key] = ", ".join(vals)
        elif ptype == "date":
            d = prop.get("date") or {}
            if d.get("start"):
                props_out[key] = d["start"]
        elif ptype == "url":
            if prop.get("url"):
                props_out[key] = prop["url"]
        elif ptype == "checkbox":
            props_out[key] = "yes" if prop.get("checkbox") else "no"
        elif ptype == "number":
            if prop.get("number") is not None:
                props_out[key] = str(prop["number"])

    # Fetch block content
    blocks_resp = requests.get(
        f"{cfg.NOTION_BASE}/blocks/{page_id}/children",
        headers=_notion_headers(),
        params={"page_size": max_blocks},
        timeout=30,
    )
    _raise_for(blocks_resp)
    blocks = blocks_resp.json().get("results", [])
    body_text = _blocks_to_text(blocks)

    return {
        "title": title,
        "url": page.get("url", ""),
        "properties": props_out,
        "body_text": body_text[:8000],  # cap for context window
        "block_count": len(blocks),
    }



def notion_list_performers_in_icpdb(limit: int = 200) -> dict:
    """Returns all performers in the ICPDB (up to `limit`) with id, name, instagram."""
    all_results = []
    has_more = True
    cursor = None
    while has_more and len(all_results) < limit:
        payload: dict[str, Any] = {
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
            # Find the title property regardless of its column name
            name = ""
            for prop in props.values():
                if prop.get("type") == "title":
                    texts = prop.get("title", [])
                    name = texts[0].get("plain_text", "") if texts else ""
                    break
            ig_texts = props.get("Instagram", {}).get("rich_text", [])
            instagram = ig_texts[0].get("plain_text", "") if ig_texts else ""
            if name:
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

def set_performer_photo(page_id: str, image_url: str) -> dict:
    """Set the 'Main photo' on an ICPDB performer page to an external image URL."""
    payload = {
        "properties": {
            "Main photo": {
                "files": [{
                    "type": "external",
                    "name": "photo",
                    "external": {"url": image_url},
                }]
            }
        }
    }
    resp = requests.patch(
        f"{cfg.NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        json=payload,
        timeout=30,
    )
    _raise_for(resp)
    return {"ok": True, "page_id": page_id}


def load_outreach_replies(months_back: int = 4) -> dict:
    """
    Return performers who have logged upcoming show info from outreach replies
    within the past months_back months. Used by Luzia as confirmed intelligence.
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=months_back * 31)).strftime("%Y-%m-%d")

    db_id = cfg.get("NOTION_ICPDB_DS")
    performers = []
    cursor = None

    while True:
        payload: dict = {
            "page_size": 100,
            "filter": {
                "and": [
                    {
                        "property": "Upcoming Shows",
                        "rich_text": {"is_not_empty": True},
                    },
                    {
                        "property": "Last Outreach Date",
                        "date": {"on_or_after": cutoff},
                    },
                ]
            },
        }
        if cursor:
            payload["start_cursor"] = cursor

        try:
            resp = requests.post(
                f"{cfg.NOTION_BASE}/databases/{db_id}/query",
                headers=_notion_headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception:
            break

        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})
            name = ""
            for prop in props.values():
                if prop.get("type") == "title":
                    texts = prop.get("title", [])
                    name = texts[0].get("plain_text", "") if texts else ""
                    break

            ig_texts = props.get("Instagram", {}).get("rich_text", [])
            instagram = ig_texts[0].get("plain_text", "").lstrip("@") if ig_texts else ""

            shows_texts = props.get("Upcoming Shows", {}).get("rich_text", [])
            upcoming_shows = shows_texts[0].get("plain_text", "") if shows_texts else ""

            notes_texts = props.get("Outreach Notes", {}).get("rich_text", [])
            notes = notes_texts[0].get("plain_text", "") if notes_texts else ""

            if upcoming_shows:
                performers.append({
                    "id": page["id"],
                    "name": name,
                    "instagram": instagram,
                    "upcoming_shows": upcoming_shows,
                    "outreach_notes": notes,
                })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return {
        "performers": performers,
        "count": len(performers),
        "note": (
            f"Logged from direct outreach replies (last {months_back} months). "
            "Treat as ✓ Confirmed."
        ) if performers else "No outreach replies logged yet.",
    }


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
