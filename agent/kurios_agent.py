"""
Kurios — Circus Jobs Agent.
Named after Cirque du Soleil's 2014 show "Kurios: Cabinet of Curiosities".

Searches the internet daily for circus and contortion job opportunities,
maintains a Notion database of live listings, and marks stale ones as
Fulfilled/Closed.  Runs autonomously on a schedule — no blocking decisions.
"""

from __future__ import annotations

from .agent_runtime import AgentContext, AgentSpec, run_loop
from .kurios_prompts import KURIOS_SYSTEM_PROMPT, KURIOS_PHASE_PROMPTS
from .kurios_tools import (
    search_circus_jobs,
    get_default_job_queries,
    list_active_jobs,
    create_job,
    update_job_seen,
    close_stale_jobs,
    sync_jobs,
)
from . import run_store

KURIOS_TOOLS: list[dict] = [
    {
        "name": "search_circus_jobs",
        "description": (
            "Search the web for circus or contortion job listings. "
            "Pass a specific query or omit for a default contortion-job search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string", "description": "Search query (optional)."},
                "max_results": {"type": "integer", "description": "Results to return (default 10)."},
            },
            "required": [],
        },
    },
    {
        "name": "get_default_job_queries",
        "description": "Return the standard set of search queries for this cycle.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_active_jobs",
        "description": "Fetch all current job listings from the Notion jobs database.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "sync_jobs",
        "description": (
            "Sync a list of found job listings to Notion: creates new ones and "
            "refreshes the Last Seen date on existing ones. "
            "Call this ONCE with ALL found listings after deduplication."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "found_listings": {
                    "type": "array",
                    "description": "All distinct job listings found this cycle.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title":       {"type": "string", "description": "Job title."},
                            "company":     {"type": "string", "description": "Hiring company or organisation."},
                            "location":    {"type": "string", "description": "Location or 'Remote' / 'Touring'."},
                            "source_url":  {"type": "string", "description": "Direct URL to the job listing."},
                            "description": {"type": "string", "description": "Brief description (1-3 sentences)."},
                            "job_type":    {
                                "type": "string",
                                "description": "Category.",
                                "enum": [
                                    "Contortion Specialist",
                                    "Aerial + Contortion",
                                    "Circus / Acrobatic",
                                    "Physical Theatre",
                                    "Other",
                                ],
                            },
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["found_listings"],
        },
    },
    {
        "name": "close_stale_jobs",
        "description": (
            "Mark Active jobs whose Last Seen date is older than stale_days as "
            "Fulfilled/Closed.  Jobs stay in the database for historical reference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stale_days": {
                    "type": "integer",
                    "description": "Days since last seen before closing (default 14).",
                },
            },
            "required": [],
        },
    },
]

TOOL_FUNCTIONS = {
    "search_circus_jobs":   search_circus_jobs,
    "get_default_job_queries": get_default_job_queries,
    "list_active_jobs":     list_active_jobs,
    "sync_jobs":            sync_jobs,
    "close_stale_jobs":     close_stale_jobs,
}

TOOL_PHASE_MAP = {
    "search_circus_jobs":      1,
    "get_default_job_queries": 1,
    "list_active_jobs":        1,
    "sync_jobs":               3,
    "close_stale_jobs":        3,
}

PHASE_LABELS = {
    1: "Search",
    2: "Deduplicate & Classify",
    3: "Sync to Notion",
}


def _make_spec(run_id: str) -> AgentSpec:
    completed: list[int] = []

    def after_tool(tool: str, inp: dict, result: dict) -> dict | None:
        phase = TOOL_PHASE_MAP.get(tool, 0)
        if phase and phase not in completed:
            completed.append(phase)
            run_store.save_phase(run_id, phase, f"phase{phase}", result)
        return None

    return AgentSpec(
        system_prompt=KURIOS_SYSTEM_PROMPT,
        tools=KURIOS_TOOLS,
        tool_functions=TOOL_FUNCTIONS,
        phase_prompts=KURIOS_PHASE_PROMPTS,
        phase_labels=PHASE_LABELS,
        after_tool=after_tool,
    )


def run_with_callbacks(
    run_id: str | None = None,
    on_event=None,
    check_pause=None,
    decide=None,        # unused — Kurios is non-interactive
) -> dict:
    """
    Run Kurios to completion.  Fully autonomous — no blocking decisions.
    on_event(type, payload) is called for progress events.
    Returns the final run record.
    """
    import time as _time
    if run_id is None:
        run_id = f"kurios-{_time.strftime('%Y-%m-%d-%H%M%S')}"

    run_store.create_run("kurios", run_id, {"run_id": run_id})

    def _emit(event_type: str, **kwargs):
        if on_event:
            on_event(event_type, kwargs)

    try:
        spec = _make_spec(run_id)
        ctx = AgentContext(
            run_id=run_id,
            on_event=_emit,
            check_pause=check_pause or (lambda: False),
            decide=decide or (lambda kind, payload: {}),
        )
        run_loop(ctx, spec)
        run_store.complete_run(run_id)
    except Exception as exc:
        run_store.fail_run(run_id, str(exc))
        _emit("error", message=str(exc))

    return run_store.get_run(run_id) or {}
