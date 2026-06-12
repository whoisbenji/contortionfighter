"""
ICPDB Maintenance Agent loop.
Structured like agent.py but drives the five-phase ICPDB workflow.
"""

from __future__ import annotations

from .agent_runtime import AgentContext, AgentSpec, run_loop
from .kooza_prompts import ICPDB_SYSTEM_PROMPT, audit_prompt
from .kooza_tools import (
    icpdb_audit,
    web_search_performer_info,
    notion_update_performer,
    draft_outreach_messages,
    merge_performer_records,
    fetch_performer_fields,
)
from . import memory as mem

# ── Tool schema definitions ───────────────────────────────────────────────────

ICPDB_TOOLS: list[dict] = [
    {
        "name": "icpdb_audit",
        "description": (
            "Audit the ICPDB: read the database schema, fetch all performer records, "
            "and compute completeness metrics. Returns total count, health score, "
            "per-field completeness, and a list of performers needing updates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "web_search_performer_info",
        "description": (
            "Search the web for public information about a contortion performer. "
            "Finds bio, nationality, website, Instagram handle. "
            "Returns deduplicated results from 1-2 targeted queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string",  "description": "Performer's full name."},
                "instagram":   {"type": "string",  "description": "Known Instagram handle (skip second search if provided)."},
                "context":     {"type": "string",  "description": "Optional context to narrow the search (e.g. show name, country)."},
                "max_results": {"type": "integer", "default": 5, "description": "Max results per search query."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "propose_performer_updates",
        "description": (
            "After completing research, call this ONCE with ALL proposed changes as a single list. "
            "The user will review each proposal and approve or reject it. "
            "Returns a decisions list. Only call after Phase 2 research is complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "proposals": {
                    "type": "array",
                    "description": "All proposed field updates found during research.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "performer_id":    {"type": "string", "description": "Notion page ID of the performer."},
                            "performer_name":  {"type": "string", "description": "Human-readable performer name."},
                            "field":           {"type": "string", "description": "Notion property name to update."},
                            "current_value":   {"type": "string", "description": "Current value (may be empty)."},
                            "proposed_value":  {"type": "string", "description": "New value to set."},
                            "source":          {"type": "string", "description": "URL where info was found."},
                            "confidence":      {"type": "string", "description": "high / medium / low"},
                        },
                        "required": ["performer_id", "performer_name", "field", "proposed_value", "source"],
                    },
                },
            },
            "required": ["proposals"],
        },
    },
    {
        "name": "notion_update_performer",
        "description": (
            "Apply approved updates to a performer's Notion page. "
            "Call once per performer with all approved fields bundled together."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Notion page ID of the performer."},
                "updates": {
                    "type": "object",
                    "description": "Dict mapping Notion field name → new value.",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["page_id", "updates"],
        },
    },
    {
        "name": "draft_outreach_messages",
        "description": (
            "Generate Instagram DM and email outreach drafts for a list of performers. "
            "Use for performers who are active but have no linked shows. "
            "Presents drafts to the user — does NOT send anything automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "performers": {
                    "type": "array",
                    "description": "Performers to draft messages for.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":        {"type": "string"},
                            "name":      {"type": "string"},
                            "instagram": {"type": "string"},
                            "email":     {"type": "string"},
                        },
                        "required": ["id", "name"],
                    },
                },
                "upcoming_months": {"type": "string", "description": "E.g. 'July 2026 and August 2026'. Auto-computed if omitted."},
            },
            "required": ["performers"],
        },
    },
    {
        "name": "propose_duplicate_resolutions",
        "description": (
            "After auditing and analysing duplicate groups, call this ONCE with ALL "
            "groups and your recommendation for each. The user will review and decide. "
            "Returns a decisions list. Call after Phase 1 audit has identified duplicates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "description": "All duplicate groups with recommendations.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "group_id":       {"type": "string", "description": "Unique identifier for this group (e.g. 'group_0')."},
                            "type":           {"type": "string", "description": "exact or suspected"},
                            "reason":         {"type": "string", "description": "Why they are flagged as duplicates."},
                            "recommendation": {"type": "string", "description": "merge or keep_both"},
                            "primary_id":     {"type": "string", "description": "Page ID of the record to keep as primary (required when recommendation=merge)."},
                            "secondary_id":   {"type": "string", "description": "Page ID of the record to archive (required when recommendation=merge)."},
                            "primary_name":   {"type": "string", "description": "Name of the primary record."},
                            "secondary_name": {"type": "string", "description": "Name of the secondary record."},
                            "primary_url":    {"type": "string", "description": "Notion URL of primary."},
                            "secondary_url":  {"type": "string", "description": "Notion URL of secondary."},
                            "rationale":      {"type": "string", "description": "Brief explanation of why this recommendation was made."},
                            "primary_completeness":   {"type": "string", "description": "Short summary of what fields primary has filled."},
                            "secondary_completeness": {"type": "string", "description": "Short summary of what fields secondary has filled."},
                        },
                        "required": ["group_id", "type", "reason", "recommendation", "rationale"],
                    },
                },
            },
            "required": ["groups"],
        },
    },
    {
        "name": "merge_performer_records",
        "description": (
            "Merge two duplicate performer pages in Notion. "
            "Copies non-empty fields from secondary into primary (only where primary is empty), "
            "then archives the secondary page. Call once per approved merge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "primary_id":   {"type": "string", "description": "Notion page ID of the record to keep."},
                "secondary_id": {"type": "string", "description": "Notion page ID of the record to archive."},
            },
            "required": ["primary_id", "secondary_id"],
        },
    },
]

# ── Tool dispatcher ───────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "icpdb_audit":               icpdb_audit,
    "web_search_performer_info": web_search_performer_info,
    "notion_update_performer":   notion_update_performer,
    "draft_outreach_messages":   draft_outreach_messages,
    "merge_performer_records":   merge_performer_records,
}

# Phase mapping
TOOL_PHASE_MAP = {
    "icpdb_audit":               (1, "Audit"),
    "web_search_performer_info": (2, "Research"),
    "propose_performer_updates": (3, "Review"),
    "notion_update_performer":   (4, "Apply"),
    "draft_outreach_messages":   (5, "Outreach"),
    "propose_duplicate_resolutions": (3, "Review"),
    "merge_performer_records":        (4, "Merge"),
}

# ── Agent spec ────────────────────────────────────────────────────────────────

def _make_spec(run_id: str | None) -> AgentSpec:
    counters = {"updated_fields_total": 0}

    def h_propose_updates(tool_input: dict, ctx: AgentContext) -> dict:
        proposals = tool_input.get("proposals", [])
        decisions = ctx.decide("update_proposals", {"proposals": proposals})
        approved_count = sum(1 for d in decisions.get("decisions", []) if d.get("approved"))
        if run_id:
            mem.save_icpdb_phase(run_id, 3, {
                "proposals_count": len(proposals),
                "approved_count":  approved_count,
            })
            ctx.on_event({"type": "phase_saved", "phase": 3})
        return decisions

    def h_propose_dedups(tool_input: dict, ctx: AgentContext) -> dict:
        groups = tool_input.get("groups", [])
        # Enrich groups with full field data so the reviewer can compare records.
        enriched = []
        for g in groups:
            eg = dict(g)
            if g.get("primary_id"):
                eg["primary_fields"] = fetch_performer_fields(g["primary_id"])
            if g.get("secondary_id"):
                eg["secondary_fields"] = fetch_performer_fields(g["secondary_id"])
            enriched.append(eg)
        return ctx.decide("duplicate_proposals", {"groups": enriched})

    def after_tool(tool_name: str, tool_input: dict, result: dict, ctx: AgentContext):
        if tool_name == "icpdb_audit" and "error" not in result:
            audit_data = {
                "total":                           result.get("total", 0),
                "health_score":                    result.get("health_score", 0),
                "completeness":                    result.get("completeness", {}),
                "performers_needing_update_count": len(result.get("performers_needing_update", [])),
                "duplicates":                      result.get("duplicates", {}),
            }
            if run_id:
                mem.save_icpdb_phase(run_id, 1, audit_data)
                ctx.on_event({"type": "phase_saved", "phase": 1})
            ctx.on_event({"type": "audit_metrics", **audit_data})

            # Compact result for the model: the full performers_needing_update
            # list can be 400+ items; send a count and top-10 sample instead.
            # Duplicate groups stay intact so the model can analyse them.
            pnu = result.get("performers_needing_update", [])
            return {
                **result,
                "performers_needing_update_count": len(pnu),
                "performers_needing_update":       pnu[:10],
            }

        if tool_name == "notion_update_performer" and "error" not in result and run_id:
            counters["updated_fields_total"] += len(result.get("updated_fields", []))
            mem.save_icpdb_phase(run_id, 4, {
                "updated_fields_total": counters["updated_fields_total"],
            })

        if tool_name == "draft_outreach_messages" and "error" not in result:
            ctx.on_event({"type": "outreach_drafts", "drafts": result.get("drafts", [])})
            if run_id:
                mem.save_icpdb_phase(run_id, 5, {"drafts_count": result.get("count", 0)})
                ctx.on_event({"type": "phase_saved", "phase": 5})

        return None

    return AgentSpec(
        name="Kooza",
        system_prompt=ICPDB_SYSTEM_PROMPT,
        tools=ICPDB_TOOLS,
        tool_functions=TOOL_FUNCTIONS,
        tool_phase_map=TOOL_PHASE_MAP,
        blocking_tools={
            "propose_performer_updates":     h_propose_updates,
            "propose_duplicate_resolutions": h_propose_dedups,
        },
        after_tool=after_tool,
    )


# ── Public entry point ────────────────────────────────────────────────────────

def run_with_callbacks(
    on_event,
    check_pause=None,
    decide=None,
    run_mode: str = "full",
    run_id: str | None = None,
    prefs: dict | None = None,
) -> str:
    """Host entry point — streams events via on_event; decisions via decide(kind, payload)."""
    if run_id is None:
        run_id = mem.create_icpdb_run(run_mode)

    on_event({"type": "run_id", "run_id": run_id})

    messages = [{"role": "user", "content": audit_prompt(run_mode, prefs=prefs)}]

    on_event({"type": "phase", "phase": 1, "label": "Audit"})

    ctx = AgentContext(on_event=on_event, check_pause=check_pause, decide=decide)

    try:
        result = run_loop(_make_spec(run_id), messages, ctx)
        mem.complete_icpdb_run(run_id)
        on_event({"type": "history_updated"})
        return result
    except Exception as exc:
        mem.fail_icpdb_run(run_id, str(exc))
        on_event({"type": "error", "message": str(exc)})
        raise
