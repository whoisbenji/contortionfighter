"""
Tool implementations for Kurios — the Circus Jobs Agent.

Kurios manages a Notion jobs database: creating new listings, updating
the Last Seen date on ones that are still live, and marking missing ones
as Fulfilled/Closed.  It also wraps web_search with circus-job-specific
queries so the agent can focus on decision-making rather than query construction.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
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
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:400]}")


def _today() -> str:
    return date.today().isoformat()


# ── Job search ────────────────────────────────────────────────────────────────

_JOB_QUERIES = [
    "contortionist job audition 2026",
    "circus contortion performer job vacancy",
    "acrobat contortionist casting call",
    "contortionist wanted circus company",
    "circus performer jobs contortion",
    "aerial contortionist audition casting",
    "contemporary circus acrobat job",
    "physical theatre contortionist",
]


def search_circus_jobs(query: str = "", max_results: int = 10) -> dict:
    """
    Search the web for circus or contortion job listings.
    If query is omitted a default contortion-job search is used.
    Returns {query, results: [{title, url, snippet}]}.
    """
    q = query or "contortionist job audition OR casting OR vacancy 2026"
    return _web_search(q, max_results=max_results)


def get_default_job_queries() -> dict:
    """Return the standard set of queries Kurios runs on each cycle."""
    return {"queries": _JOB_QUERIES}


# ── Notion jobs database ──────────────────────────────────────────────────────

def _jobs_db_id() -> str:
    return cfg.get("NOTION_JOBS_DS")


def list_active_jobs() -> dict:
    """
    Query the jobs database for all non-archived entries.
    Returns {jobs: [{id, title, url, status, company, last_seen, date_found}]}.
    """
    db_id = _jobs_db_id()
    if not db_id:
        return {"jobs": [], "count": 0, "warning": "NOTION_JOBS_DS is not configured. Set it in Admin Settings → Circus Jobs DB."}
    jobs: list[dict] = []
    cursor = None

    while True:
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

        for page in data.get("results", []):
            if page.get("archived"):
                continue
            props = page.get("properties", {})

            def _text(key: str) -> str:
                p = props.get(key, {})
                ptype = p.get("type", "")
                if ptype == "title":
                    texts = p.get("title", [])
                elif ptype == "rich_text":
                    texts = p.get("rich_text", [])
                elif ptype == "url":
                    return p.get("url") or ""
                else:
                    texts = []
                return texts[0].get("plain_text", "") if texts else ""

            def _select(key: str) -> str:
                sel = props.get(key, {}).get("select") or {}
                return sel.get("name", "")

            def _date(key: str) -> str:
                d = props.get(key, {}).get("date") or {}
                return d.get("start", "")

            jobs.append({
                "id":         page["id"],
                "notion_url": page.get("url", ""),
                "title":      _text("Job Title"),
                "company":    _text("Company"),
                "location":   _text("Location"),
                "source_url": _text("Source URL"),
                "status":     _select("Status"),
                "job_type":   _select("Job Type"),
                "last_seen":  _date("Last Seen"),
                "date_found": _date("Date Found"),
            })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return {"jobs": jobs, "count": len(jobs)}


def create_job(
    title: str,
    company: str = "",
    location: str = "",
    source_url: str = "",
    description: str = "",
    job_type: str = "Circus / Acrobatic",
) -> dict:
    if not _jobs_db_id():
        raise RuntimeError("NOTION_JOBS_DS is not configured — paste the Circus Jobs database ID into Admin Settings.")
    """
    Create a new job listing in the Notion jobs database.
    job_type must be one of: Contortion Specialist, Aerial + Contortion,
    Circus / Acrobatic, Physical Theatre, Other.
    Returns {page_id, notion_url}.
    """
    today = _today()
    properties: dict[str, Any] = {
        "Job Title": {"title": [{"text": {"content": title}}]},
        "Status":    {"select": {"name": "Active"}},
        "Job Type":  {"select": {"name": job_type}},
        "Date Found": {"date": {"start": today}},
        "Last Seen":  {"date": {"start": today}},
    }
    if company:
        properties["Company"] = {"rich_text": [{"text": {"content": company}}]}
    if location:
        properties["Location"] = {"rich_text": [{"text": {"content": location}}]}
    if source_url:
        properties["Source URL"] = {"url": source_url}

    payload: dict[str, Any] = {
        "parent": {"database_id": _jobs_db_id()},
        "properties": properties,
    }
    if description:
        from .tools import _paragraph, _markdown_to_notion_blocks
        payload["children"] = _markdown_to_notion_blocks(description)[:100]

    resp = requests.post(
        f"{cfg.NOTION_BASE}/pages",
        headers=_notion_headers(),
        json=payload,
        timeout=30,
    )
    _raise_for(resp)
    page = resp.json()
    return {"page_id": page["id"], "notion_url": page.get("url", ""), "title": title}


def update_job_seen(page_id: str) -> dict:
    """
    Refresh the Last Seen date on an existing job to today.
    Also ensures its Status is Active (in case it was previously Closed).
    """
    today = _today()
    resp = requests.patch(
        f"{cfg.NOTION_BASE}/pages/{page_id}",
        headers=_notion_headers(),
        json={
            "properties": {
                "Last Seen": {"date": {"start": today}},
                "Status":    {"select": {"name": "Active"}},
            }
        },
        timeout=30,
    )
    _raise_for(resp)
    return {"ok": True, "page_id": page_id, "last_seen": today}


def close_stale_jobs(stale_days: int = 14) -> dict:
    """
    Mark as Fulfilled/Closed any Active jobs whose Last Seen date is more
    than stale_days ago.  Closed jobs stay in the database for historical
    reference — they are never deleted or archived.
    Returns {closed: [{id, title, last_seen}], count}.
    """
    cutoff = (date.today() - timedelta(days=stale_days)).isoformat()
    result = list_active_jobs()
    closed = []

    for job in result["jobs"]:
        if job["status"] != "Active":
            continue
        last_seen = job.get("last_seen", "")
        if not last_seen or last_seen <= cutoff:
            resp = requests.patch(
                f"{cfg.NOTION_BASE}/pages/{job['id']}",
                headers=_notion_headers(),
                json={"properties": {"Status": {"select": {"name": "Fulfilled/Closed"}}}},
                timeout=30,
            )
            _raise_for(resp)
            closed.append({"id": job["id"], "title": job["title"], "last_seen": last_seen})

    return {"closed": closed, "count": len(closed)}


def sync_jobs(found_listings: list[dict]) -> dict:
    """
    The core sync operation.  Given a list of listings discovered this run
    (each with title, source_url, company, location, description, job_type),
    this function:
      1. Loads all current active jobs from Notion.
      2. For each found listing: if a job with the same source_url already
         exists, refreshes its Last Seen date; otherwise creates it.
      3. Returns a summary {created, refreshed, skipped}.

    Matching is by source_url (exact) — if a listing has no URL it is
    always created (de-duplication is imperfect without a stable identifier).
    """
    existing = list_active_jobs()
    by_url: dict[str, dict] = {}
    for job in existing["jobs"]:
        url = job.get("source_url", "").strip()
        if url:
            by_url[url] = job

    created: list[dict] = []
    refreshed: list[dict] = []
    skipped: list[str] = []

    for listing in found_listings:
        url = listing.get("source_url", "").strip()
        if url and url in by_url:
            update_job_seen(by_url[url]["id"])
            refreshed.append({"title": listing.get("title", ""), "url": url})
        else:
            title = listing.get("title", "Untitled")
            if not title or title == "Untitled":
                skipped.append(url or "(no url)")
                continue
            result = create_job(
                title=title,
                company=listing.get("company", ""),
                location=listing.get("location", ""),
                source_url=url,
                description=listing.get("description", ""),
                job_type=listing.get("job_type", "Circus / Acrobatic"),
            )
            created.append(result)

    return {
        "created":   created,
        "created_count":   len(created),
        "refreshed": refreshed,
        "refreshed_count": len(refreshed),
        "skipped":   skipped,
        "skipped_count":   len(skipped),
    }
