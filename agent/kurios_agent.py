"""
Kurios — Circus Jobs Agent.
Named after Cirque du Soleil's 2014 show "Kurios: Cabinet of Curiosities".

Searches the internet daily for circus and contortion job opportunities,
maintains a Notion database of live listings, and marks stale ones as
Fulfilled/Closed.  Runs autonomously on a schedule — no blocking decisions.
"""

from __future__ import annotations

from .agent_runtime import AgentContext, AgentSpec, run_loop
from .kurios_prompts import KURIOS_SYSTEM_PROMPT, kickoff_prompt
from .kurios_tools import (
    search_circus_jobs,
    get_default_job_queries,
    list_active_jobs,
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
    "search_circus_jobs":      search_circus_jobs,
    "get_default_job_queries": get_default_job_queries,
    "list_active_jobs":        list_active_jobs,
    "sync_jobs":               sync_jobs,
    "close_stale_jobs":        close_stale_jobs,
}

# tool_name -> (phase number, phase label)
TOOL_PHASE_MAP = {
    "get_default_job_queries": (1, "Search"),
    "search_circus_jobs":      (1, "Search"),
    "list_active_jobs":        (1, "Search"),
    "sync_jobs":               (3, "Sync to Notion"),
    "close_stale_jobs":        (3, "Sync to Notion"),
}


def _make_spec(run_id: str | None) -> AgentSpec:

    def after_tool(tool_name: str, tool_input: dict, result: dict, ctx: AgentContext):
        if tool_name == "sync_jobs" and isinstance(result, dict) and "error" not in result:
            if run_id:
                run_store.save_phase(run_id, 3, "phase3", {
                    "created_count":   result.get("created_count", 0),
                    "refreshed_count": result.get("refreshed_count", 0),
                    "skipped_count":   result.get("skipped_count", 0),
                })
            ctx.on_event({"type": "jobs_synced",
                          "created":   result.get("created_count", 0),
                          "refreshed": result.get("refreshed_count", 0)})
        if tool_name == "close_stale_jobs" and isinstance(result, dict) and "error" not in result:
            if run_id:
                run_store.save_phase(run_id, 3, "phase3_closed", {"closed_count": result.get("count", 0)})
        return None

    return AgentSpec(
        name="Kurios",
        system_prompt=KURIOS_SYSTEM_PROMPT,
        tools=KURIOS_TOOLS,
        tool_functions=TOOL_FUNCTIONS,
        tool_phase_map=TOOL_PHASE_MAP,
        after_tool=after_tool,
    )


def run_with_callbacks(
    on_event,
    check_pause=None,
    decide=None,        # unused — Kurios is non-interactive
    run_id: str | None = None,
) -> str:
    """
    Run Kurios to completion. Fully autonomous — no blocking decisions.
    on_event(event_dict) receives progress events. Returns the final text.
    """
    import time as _time
    if run_id is None:
        run_id = f"kurios-{_time.strftime('%Y-%m-%d-%H%M%S')}"
        run_id = run_store.create_run("kurios", run_id, {"run_id": run_id})

    on_event({"type": "run_id", "run_id": run_id})
    on_event({"type": "phase", "phase": 1, "label": "Search"})

    messages = [{"role": "user", "content": kickoff_prompt()}]
    ctx = AgentContext(on_event=on_event, check_pause=check_pause, decide=decide)

    try:
        result = run_loop(_make_spec(run_id), messages, ctx)
        run_store.complete_run(run_id)
        on_event({"type": "done"})
        return result
    except Exception as exc:
        run_store.fail_run(run_id, str(exc))
        on_event({"type": "error", "message": str(exc)})
        raise
