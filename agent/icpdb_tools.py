"""
Tool implementations for the ICPDB Maintenance Agent.
Talks to Notion to audit, research, and update performer records.
"""

from __future__ import annotations
import os
import time
import urllib.parse
from typing import Any

import requests

from . import config as cfg
from .tools import web_search as _web_search


# ── Helpers ───────────────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    key = os.environ["NOTION_API_KEY"]
    return {
        "Authorization": f"Bearer {key}",
        "Notion-Version": cfg.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _raise_for(resp: requests.Response) -> None:
    if not resp.ok:
        msg = resp.text[:400]
        raise RuntimeError(f"HTTP {resp.status_code}: {msg}")


_SKIP_TYPES = {
    "formula", "rollup", "created_time", "last_edited_time",
    "created_by", "last_edited_by", "unique_id",
}


def _prop_value(prop: dict) -> str:
    """Extract a string value from any Notion property object."""
    ptype = prop.get("type", "")
    if ptype in _SKIP_TYPES:
        return ""
    val = prop.get(ptype)
    if val is None:
        return ""
    if ptype == "title":
        texts = val if isinstance(val, list) else []
        return texts[0].get("plain_text", "") if texts else ""
    if ptype == "rich_text":
        texts = val if isinstance(val, list) else []
        return texts[0].get("plain_text", "") if texts else ""
    if ptype == "select":
        return val.get("name", "") if val else ""
    if ptype == "multi_select":
        return ", ".join(v.get("name", "") for v in val) if val else ""
    if ptype == "url":
        return val or ""
    if ptype == "email":
        return val or ""
    if ptype == "phone_number":
        return val or ""
    if ptype == "checkbox":
        return "true" if val else ""
    if ptype == "number":
        return str(val) if val is not None else ""
    if ptype == "date":
        return val.get("start", "") if val else ""
    if ptype == "relation":
        return str(len(val)) if val else ""
    if ptype == "people":
        return ", ".join(p.get("name", "") for p in val) if val else ""
    if ptype == "files":
        return val[0].get("name", "") if val else ""
    return str(val) if val else ""


def _has_value(prop: dict) -> bool:
    return bool(_prop_value(prop))


# ── Main tools ────────────────────────────────────────────────────────────────

def icpdb_audit() -> dict:
    """
    Audit the ICPDB: read schema, query all performers, compute completeness metrics.
    """
    notion_key = os.environ.get("NOTION_API_KEY", "")
    if not notion_key:
        return {"error": "NOTION_API_KEY is not set"}

    db_id = cfg.get("NOTION_ICPDB_DS")

    # Fetch schema
    schema_resp = requests.get(
        f"{cfg.NOTION_BASE}/databases/{db_id}",
        headers=_notion_headers(),
        timeout=30,
    )
    _raise_for(schema_resp)
    schema = schema_resp.json()
    all_props = schema.get("properties", {})

    # Determine which properties are trackable
    trackable_fields: list[str] = []
    title_field: str = ""
    for name, prop in all_props.items():
        ptype = prop.get("type", "")
        if ptype in _SKIP_TYPES:
            continue
        if ptype == "title":
            title_field = name
        else:
            trackable_fields.append(name)

    # Paginate through all performers
    all_pages: list[dict] = []
    cursor = None
    has_more = True
    while has_more:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(
            f"{cfg.NOTION_BASE}/databases/{db_id}/query",
            headers=_notion_headers(),
            json=payload,
            timeout=30,
        )
        _raise_for(resp)
        data = resp.json()
        all_pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")

    total = len(all_pages)

    # Compute completeness per field
    field_counts: dict[str, int] = {f: 0 for f in trackable_fields}
    performers_needing_update: list[dict] = []

    for page in all_pages:
        props = page.get("properties", {})

        # Get name via title field
        name = ""
        if title_field and title_field in props:
            name = _prop_value(props[title_field])
        if not name:
            for prop in props.values():
                if prop.get("type") == "title":
                    name = _prop_value(prop)
                    break

        # Get instagram & url for reference
        instagram = _prop_value(props.get("Instagram", {})) if "Instagram" in props else ""
        url = page.get("url", "")

        missing_fields: list[str] = []
        for field in trackable_fields:
            prop = props.get(field, {})
            if _has_value(prop):
                field_counts[field] += 1
            else:
                missing_fields.append(field)

        if missing_fields and name:
            performers_needing_update.append({
                "id": page["id"],
                "name": name,
                "url": url,
                "instagram": instagram,
                "missing_fields": missing_fields,
                "missing_count": len(missing_fields),
            })

    # Sort by most missing
    performers_needing_update.sort(key=lambda p: p["missing_count"], reverse=True)

    # Completeness stats
    completeness: dict[str, dict] = {}
    for field in trackable_fields:
        has = field_counts[field]
        missing = total - has
        pct = round(has / total * 100) if total else 0
        completeness[field] = {"has": has, "missing": missing, "pct": pct}

    # Overall health score: average completeness across all trackable fields
    if trackable_fields and total:
        total_pct = sum(completeness[f]["pct"] for f in trackable_fields)
        health_score = round(total_pct / len(trackable_fields))
    else:
        health_score = 0

    return {
        "total": total,
        "health_score": health_score,
        "completeness": completeness,
        "performers_needing_update": performers_needing_update,
        "title_field": title_field,
        "trackable_fields": trackable_fields,
    }


def web_search_performer_info(
    name: str,
    instagram: str = "",
    context: str = "",
    max_results: int = 5,
) -> dict:
    """Search the web for info about a contortion performer."""
    query1 = f'"{name}" contortionist'
    if context:
        query1 += f" {context}"
    results1 = _web_search(query1, max_results=max_results).get("results", [])

    results2: list[dict] = []
    if not instagram:
        query2 = f'"{name}" contortionist instagram'
        results2 = _web_search(query2, max_results=max_results).get("results", [])

    all_results = results1 + results2
    # Deduplicate by URL
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(r)

    return {
        "query": query1,
        "results": deduped,
    }


def notion_update_performer(page_id: str, updates: dict) -> dict:
    """Update fields on a performer page in Notion."""
    # Fetch current page to know property types
    get_resp = requests.get(
        f"{cfg.NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        timeout=30,
    )
    _raise_for(get_resp)
    page_data = get_resp.json()
    existing_props = page_data.get("properties", {})

    properties: dict = {}
    updated_fields: list[str] = []

    for field, value in updates.items():
        if field not in existing_props:
            continue
        existing = existing_props[field]
        ptype = existing.get("type", "")

        if ptype == "rich_text":
            properties[field] = {"rich_text": [{"text": {"content": str(value)}}]}
        elif ptype == "title":
            properties[field] = {"title": [{"text": {"content": str(value)}}]}
        elif ptype == "select":
            properties[field] = {"select": {"name": str(value)}}
        elif ptype == "multi_select":
            if isinstance(value, list):
                properties[field] = {"multi_select": [{"name": str(v)} for v in value]}
            else:
                properties[field] = {"multi_select": [{"name": str(value)}]}
        elif ptype == "url":
            properties[field] = {"url": str(value)}
        elif ptype == "email":
            properties[field] = {"email": str(value)}
        elif ptype == "phone_number":
            properties[field] = {"phone_number": str(value)}
        elif ptype == "checkbox":
            properties[field] = {"checkbox": bool(value)}
        elif ptype == "number":
            properties[field] = {"number": float(value)}
        else:
            # Unknown / unsupported type — skip
            continue

        updated_fields.append(field)

    if not properties:
        return {"ok": False, "updated_fields": [], "page_id": page_id, "error": "No valid fields to update"}

    patch_resp = requests.patch(
        f"{cfg.NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        json={"properties": properties},
        timeout=30,
    )
    _raise_for(patch_resp)

    return {"ok": True, "updated_fields": updated_fields, "page_id": page_id}


def draft_outreach_messages(
    performers: list[dict],
    upcoming_months: str = "",
) -> dict:
    """Draft Instagram DM and email outreach messages for a list of performers."""
    if not upcoming_months:
        t = time.localtime()
        months = []
        for i in range(1, 3):
            m = (t.tm_mon - 1 + i) % 12 + 1
            y = t.tm_year + ((t.tm_mon - 1 + i) // 12)
            month_name = time.strftime("%B", time.strptime(f"{y}-{m:02d}-01", "%Y-%m-%d"))
            months.append(f"{month_name} {y}")
        upcoming_months = " and ".join(months)

    drafts: list[dict] = []
    for p in performers:
        pid   = p.get("id", "")
        name  = p.get("name", "")
        ig    = p.get("instagram", "").lstrip("@")
        email = p.get("email", "")

        ig_url = f"https://instagram.com/{ig}" if ig else ""

        instagram_dm = (
            f"Hi {name}! 👋 I run contortion.space, a platform dedicated to celebrating "
            f"contortion performers worldwide. We'd love to feature your upcoming shows for "
            f"{upcoming_months} — could you share any performances or events you have coming up? "
            f"We're always looking to shine a spotlight on amazing artists like you! 🌟"
        )

        email_subject = f"Featured Contortion Performer Opportunity – {name}"
        email_body = (
            f"Dear {name},\n\n"
            f"My name is [Your Name], and I manage contortion.space — a platform dedicated to "
            f"showcasing contortion performers from around the world.\n\n"
            f"We are compiling our performance roundup for {upcoming_months} and would love to "
            f"include your upcoming shows and appearances. Could you let us know about any "
            f"performances, events, or engagements you have scheduled?\n\n"
            f"We appreciate your time and look forward to featuring your incredible work.\n\n"
            f"Best regards,\n"
            f"The Contortion Space Team\n"
            f"contortion.space"
        )

        mailto = ""
        if email:
            subject_enc = urllib.parse.quote(email_subject)
            body_enc = urllib.parse.quote(email_body)
            mailto = f"mailto:{email}?subject={subject_enc}&body={body_enc}"

        drafts.append({
            "performer_id":    pid,
            "name":            name,
            "instagram":       ig,
            "email":           email,
            "instagram_dm":    instagram_dm,
            "instagram_url":   ig_url,
            "email_subject":   email_subject,
            "email_body":      email_body,
            "mailto":          mailto,
        })

    return {"drafts": drafts, "count": len(drafts)}
