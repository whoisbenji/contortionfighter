"""
Tool implementations for Kurios — the Circus Jobs Agent.

Kurios manages a Notion jobs database: creating new listings, updating
the Last Seen date on ones that are still live, and marking missing ones
as Fulfilled/Closed.  It also wraps web_search with circus-job-specific
queries so the agent can focus on decision-making rather than query construction.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

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


# ── Job Sources database ──────────────────────────────────────────────────────

def _sources_db_id() -> str:
    return cfg.get("NOTION_JOB_SOURCES_DS")


def list_job_sources() -> dict:
    """
    Fetch all job sources from the Job Sources Notion database.
    Returns {sources: [{id, name, url, source_type, last_scanned}]}.
    If the DB is not configured, returns an empty list with a warning.
    """
    db_id = _sources_db_id()
    if not db_id:
        return {"sources": [], "count": 0,
                "warning": "NOTION_JOB_SOURCES_DS is not configured. Set it in Admin Settings → Job Sources DB."}

    sources: list[dict] = []
    cursor = None
    while True:
        payload: dict = {"page_size": 100}
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

            def _rollup_count(key: str) -> int:
                r = props.get(key, {}).get("rollup", {})
                return r.get("number") or 0

            sources.append({
                "id":           page["id"],
                "notion_url":   page.get("url", ""),
                "name":         _text("Name"),
                "url":          _text("URL"),
                "source_type":  _select("Source Type"),
                "last_scanned": _date("Last Scanned"),
                "listing_count": _rollup_count("Listing Count"),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return {"sources": sources, "count": len(sources)}


def upsert_job_source(name: str, url: str = "", source_type: str = "Job Board") -> dict:
    """
    Create or update a job source in the Job Sources database.
    If a source with the same name already exists, refreshes its Last Scanned date.
    Returns {page_id, notion_url, action: created|refreshed}.
    """
    db_id = _sources_db_id()
    if not db_id:
        return {"warning": "NOTION_JOB_SOURCES_DS is not configured — skipping source upsert."}

    existing = list_job_sources()
    for src in existing.get("sources", []):
        if src["name"].strip().lower() == name.strip().lower():
            resp = requests.patch(
                f"{cfg.NOTION_BASE}/pages/{src['id']}",
                headers=_notion_headers(),
                json={"properties": {"Last Scanned": {"date": {"start": _today()}}}},
                timeout=30,
            )
            _raise_for(resp)
            return {"page_id": src["id"], "notion_url": src["notion_url"], "action": "refreshed", "name": name}

    properties: dict = {
        "Name":         {"title": [{"text": {"content": name}}]},
        "Source Type":  {"select": {"name": source_type}},
        "Last Scanned": {"date": {"start": _today()}},
    }
    if url:
        properties["URL"] = {"url": url}

    resp = requests.post(
        f"{cfg.NOTION_BASE}/pages",
        headers=_notion_headers(),
        json={"parent": {"database_id": db_id}, "properties": properties},
        timeout=30,
    )
    _raise_for(resp)
    page = resp.json()
    return {"page_id": page["id"], "notion_url": page.get("url", ""), "action": "created", "name": name}


def search_source_site(source_name: str, source_url: str = "", max_results: int = 10) -> dict:
    """
    Run a targeted web search for circus/contortion jobs at a specific source site.
    Returns {source_name, query, results: [{title, url, snippet}]}.
    """
    domain = ""
    if source_url:
        import re
        m = re.search(r"https?://(?:www\.)?([^/]+)", source_url)
        if m:
            domain = m.group(1)

    if domain:
        query = f"site:{domain} contortionist OR circus performer OR acrobat job OR audition OR casting"
    else:
        query = f"{source_name} contortionist circus performer job audition"

    result = _web_search(query, max_results=max_results)
    result["source_name"] = source_name
    return result


def fetch_listing_urls(page_url: str, max_links: int = 20) -> dict:
    """
    Fetch a job listing page and extract links that look like individual job postings.
    Use this when a search result points to a general listings page rather than a
    specific job ad — call it to get direct links to individual postings.
    Returns {page_url, individual_links: [{url, text}], is_general_page: bool}.
    """
    try:
        resp = requests.get(
            page_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ContortionSpace/1.0; +https://contortionspace.com)"},
            timeout=15,
            allow_redirects=True,
        )
    except Exception as exc:
        return {"page_url": page_url, "error": str(exc), "individual_links": []}

    if not resp.ok:
        return {"page_url": page_url, "error": f"HTTP {resp.status_code}", "individual_links": []}

    html = resp.text
    base = page_url

    # Extract all <a href> links with their text
    raw_links = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)

    base_parsed = urlparse(page_url)
    base_domain = base_parsed.netloc

    # Heuristics for "this looks like an individual job posting link"
    _JOB_PATH_PATTERNS = re.compile(
        r'/(job|jobs|position|posting|vacancy|opening|role|audition|casting|listing|opportunity|apply|career)s?/'
        r'|[/-](\d{4,})'           # numeric ID in path
        r'|/(view|detail|show)/',
        re.I,
    )
    _EXCLUDE_PATTERNS = re.compile(
        r'(login|signup|register|contact|about|faq|blog|news|category|tag|page/\d|#|mailto:|javascript:)',
        re.I,
    )
    _CIRCUS_TERMS = re.compile(
        r'(contortion|circus|acrobat|aerial|performer|dance|theatre|cabaret|variety|cruise|entertainment)',
        re.I,
    )

    individual_links = []
    seen_urls = set()

    for href, link_text in raw_links:
        href = href.strip()
        if not href or href.startswith('#') or href.startswith('javascript:') or href.startswith('mailto:'):
            continue

        absolute = urljoin(base, href)
        parsed = urlparse(absolute)

        # Stay on the same domain
        if parsed.netloc and parsed.netloc != base_domain:
            continue
        if _EXCLUDE_PATTERNS.search(absolute):
            continue
        if absolute in seen_urls or absolute == page_url:
            continue

        clean_text = re.sub(r'<[^>]+>', '', link_text).strip()

        is_job_path = bool(_JOB_PATH_PATTERNS.search(parsed.path))
        has_circus_term = bool(_CIRCUS_TERMS.search(clean_text) or _CIRCUS_TERMS.search(absolute))

        if is_job_path or has_circus_term:
            seen_urls.add(absolute)
            individual_links.append({"url": absolute, "text": clean_text[:120]})
            if len(individual_links) >= max_links:
                break

    # Decide if the original URL looks like a general listing page
    general_page_patterns = re.compile(r'/(jobs|positions|vacancies|openings|auditions|casting|careers)/?$', re.I)
    is_general_page = bool(general_page_patterns.search(urlparse(page_url).path)) or len(individual_links) > 3

    return {
        "page_url": page_url,
        "individual_links": individual_links,
        "is_general_page": is_general_page,
        "count": len(individual_links),
    }


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
    source_page_id: str = "",
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
    if source_page_id:
        properties["Source"] = {"relation": [{"id": source_page_id}]}

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


def sync_jobs(found_listings: list[dict], source_page_ids: dict | None = None) -> dict:
    """
    The core sync operation.  Given a list of listings discovered this run
    (each with title, source_url, company, location, description, job_type,
    and optionally source_name mapping to a source page ID in source_page_ids),
    this function:
      1. Loads all current active jobs from Notion.
      2. For each found listing: if a job with the same source_url already
         exists, refreshes its Last Seen date; otherwise creates it.
      3. Links new jobs to their source via a Notion relation if source_page_ids provided.
      4. Returns a summary {created, refreshed, skipped}.

    source_page_ids: dict mapping source_name -> Notion page ID for the source.
    Matching is by source_url (exact) — if a listing has no URL it is
    always created (de-duplication is imperfect without a stable identifier).
    """
    source_page_ids = source_page_ids or {}
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
        source_name = listing.get("source_name", "")
        source_page_id = source_page_ids.get(source_name) if source_name else None

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
                source_page_id=source_page_id,
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
