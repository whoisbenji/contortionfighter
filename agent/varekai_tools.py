"""
Varekai — Outreach Agent tools.

Handles eligibility filtering, send-tracking, and reply logging.
All Notion writes use the same PATCH pattern as kooza_tools.py.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import requests

from . import config as cfg
from .config import NOTION_BASE, NOTION_VERSION


OUTREACH_CUTOFF_DAYS = 75  # don't re-contact within this many days


def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _raise_for(resp: requests.Response) -> None:
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:400]}")


def _prop_text(prop: dict) -> str:
    """Extract plain text from a rich_text or title property."""
    texts = prop.get("rich_text") or prop.get("title") or []
    return texts[0].get("plain_text", "") if texts else ""


def _prop_date(prop: dict) -> str | None:
    """Extract ISO date string from a date property."""
    d = prop.get("date")
    return d.get("start") if d else None


def _prop_select(prop: dict) -> str:
    s = prop.get("select")
    return s.get("name", "") if s else ""


# ── Eligibility ───────────────────────────────────────────────────────────────

def check_eligibility(performers: list[dict]) -> dict:
    """
    Filter performers to those eligible for outreach.
    Each performer dict should have: id, name, instagram, plus optionally
    last_outreach_date, outreach_response fetched from Notion.

    Returns {eligible: [...], skipped: [...], missing_fields: bool}
    """
    cutoff = datetime.utcnow() - timedelta(days=OUTREACH_CUTOFF_DAYS)
    eligible = []
    skipped = []
    missing_fields_warned = False

    for p in performers:
        name = p.get("name", "")
        ig = p.get("instagram", "").strip().lstrip("@")

        if not ig:
            skipped.append({**p, "reason": "No Instagram handle"})
            continue

        last_date_str = p.get("last_outreach_date")
        response = p.get("outreach_response", "")

        if last_date_str is None and response == "":
            missing_fields_warned = True

        if response == "Unsubscribed":
            skipped.append({**p, "reason": "Unsubscribed"})
            continue

        if last_date_str:
            try:
                last_date = datetime.fromisoformat(last_date_str[:10])
                if last_date > cutoff:
                    days_ago = (datetime.utcnow() - last_date).days
                    skipped.append({**p, "reason": f"Contacted {days_ago}d ago (< {OUTREACH_CUTOFF_DAYS}d)"})
                    continue
            except ValueError:
                pass

        eligible.append({**p, "instagram": ig})

    return {
        "eligible": eligible,
        "skipped": skipped,
        "missing_fields": missing_fields_warned,
        "eligible_count": len(eligible),
        "skipped_count": len(skipped),
    }


def fetch_performers_with_outreach_fields() -> list[dict]:
    """
    Fetch all ICPDB performers including outreach tracking fields.
    Returns list of performer dicts ready for check_eligibility().
    """
    db_id = cfg.get("NOTION_ICPDB_DS")
    performers = []
    cursor = None

    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(
            f"{NOTION_BASE}/databases/{db_id}/query",
            headers=_notion_headers(),
            json=payload,
            timeout=30,
        )
        _raise_for(resp)
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            # Title / name
            name = ""
            for prop in props.values():
                if prop.get("type") == "title":
                    texts = prop.get("title", [])
                    name = texts[0].get("plain_text", "") if texts else ""
                    break

            ig_texts = props.get("Instagram", {}).get("rich_text", [])
            instagram = ig_texts[0].get("plain_text", "").lstrip("@") if ig_texts else ""

            last_outreach = _prop_date(props.get("Last Outreach Date", {}))
            outreach_response = _prop_select(props.get("Outreach Response", {}))

            if name:
                performers.append({
                    "id": page["id"],
                    "name": name,
                    "instagram": instagram,
                    "last_outreach_date": last_outreach,
                    "outreach_response": outreach_response,
                })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return performers


# ── Tracking writes ───────────────────────────────────────────────────────────

def record_outreach_sent(page_id: str) -> dict:
    """Mark a performer as contacted today in Notion."""
    today = time.strftime("%Y-%m-%d")
    payload = {
        "properties": {
            "Last Outreach Date": {"date": {"start": today}},
            "Outreach Response":  {"select": {"name": "No Response"}},
        }
    }
    resp = requests.patch(
        f"{NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        json=payload,
        timeout=30,
    )
    _raise_for(resp)
    return {"ok": True, "page_id": page_id, "date": today}


def log_outreach_reply(
    page_id: str,
    reply_text: str,
    status: str = "Replied",
    upcoming_shows: str = "",
) -> dict:
    """Log a performer's reply and any upcoming show info to Notion."""
    valid_statuses = {"Replied", "No Response", "Unsubscribed"}
    if status not in valid_statuses:
        status = "Replied"

    props: dict = {
        "Outreach Response": {"select": {"name": status}},
    }
    if reply_text.strip():
        props["Outreach Notes"] = {
            "rich_text": [{"text": {"content": reply_text[:2000]}}]
        }
    if upcoming_shows.strip():
        props["Upcoming Shows"] = {
            "rich_text": [{"text": {"content": upcoming_shows[:2000]}}]
        }

    resp = requests.patch(
        f"{NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        json={"properties": props},
        timeout=30,
    )
    _raise_for(resp)
    return {"ok": True, "page_id": page_id, "status": status}
