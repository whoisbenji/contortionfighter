"""
ICPDB Maintenance Agent loop.
Structured like agent.py but drives the five-phase ICPDB workflow.
"""

from __future__ import annotations
import json
import os
import time
from typing import Any

import anthropic

from .icpdb_prompts import ICPDB_SYSTEM_PROMPT, audit_prompt
from .icpdb_tools import (
    icpdb_audit,
    web_search_performer_info,
    notion_update_performer,
    draft_outreach_messages,
    merge_performer_records,
)
from . import memory as mem

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

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

_NOOP_EVENT   = lambda event: None
_NOOP_PAUSE   = lambda: None
_NOOP_DECISIONS = lambda proposals: {"decisions": [{"performer_id": p["performer_id"], "approved": False} for p in proposals]}


def _dispatch(tool_name: str, tool_input: dict) -> Any:
    fn = TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(**tool_input)
    except Exception as exc:
        return {"error": str(exc)}


def _create_message_with_retry(client, **kwargs):
    """Call client.messages.create with exponential backoff on rate-limit errors."""
    delays = [10, 30, 60, 120]
    for attempt, delay in enumerate(delays + [None]):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            if delay is None:
                raise
            time.sleep(delay)
        except anthropic.APIStatusError as exc:
            if exc.status_code == 429 and delay is not None:
                time.sleep(delay)
            else:
                raise


# ── Core loop ─────────────────────────────────────────────────────────────────

def _loop(
    messages: list[dict],
    on_event,
    check_pause,
    get_update_decisions,
    run_id: str,
    verbose: bool,
    tools_override: list[dict] | None = None,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    active_tools = tools_override if tools_override is not None else ICPDB_TOOLS
    current_phase = 0

    # Accumulators for phase summaries
    _updated_fields_total = 0

    while True:
        on_event({"type": "thinking"})

        response = _create_message_with_retry(
            client,
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=ICPDB_SYSTEM_PROMPT,
            tools=active_tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            on_event({"type": "summary", "text": final_text})
            if verbose:
                print("\n✅ ICPDB Agent complete.\n")
                print(final_text)
            return final_text

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name  = block.name
            tool_input = block.input

            phase_num, phase_label = TOOL_PHASE_MAP.get(tool_name, (current_phase, "Working"))
            if phase_num != current_phase:
                current_phase = phase_num
                on_event({"type": "phase", "phase": phase_num, "label": phase_label})

            on_event({
                "type":  "tool_call",
                "tool":  tool_name,
                "input": {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
                          for k, v in tool_input.items()},
            })

            if verbose:
                print(f"\n🔧 {tool_name}: {json.dumps(tool_input)[:200]}")

            # ── propose_performer_updates: blocking review ────────────────
            if tool_name == "propose_performer_updates":
                proposals = tool_input.get("proposals", [])
                on_event({"type": "update_proposals", "proposals": proposals})
                decisions = get_update_decisions(proposals)
                # Save phase 3 summary
                approved_count = sum(1 for d in decisions.get("decisions", []) if d.get("approved"))
                if run_id:
                    mem.save_icpdb_phase(run_id, 3, {
                        "proposals_count": len(proposals),
                        "approved_count": approved_count,
                    })
                    on_event({"type": "phase_saved", "phase": 3})
                result_str = json.dumps(decisions)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result_str,
                })
                on_event({
                    "type":   "tool_result",
                    "tool":   tool_name,
                    "result": result_str[:500],
                    "ok":     True,
                })
                continue

            # ── propose_duplicate_resolutions: blocking review ────────────
            if tool_name == "propose_duplicate_resolutions":
                groups = tool_input.get("groups", [])
                on_event({"type": "duplicate_proposals", "groups": groups})
                decisions = get_update_decisions(groups)   # reuse the same queue
                result_str = json.dumps(decisions)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result_str,
                })
                on_event({
                    "type":   "tool_result",
                    "tool":   tool_name,
                    "result": result_str[:500],
                    "ok":     True,
                })
                continue

            # ── Pause / interject check ───────────────────────────────────
            interject = check_pause()
            if interject:
                messages.append({"role": "user", "content": (
                    f"[User interjection]: {interject}\n"
                    "Please take this into account and adjust your next action accordingly."
                )})
                on_event({"type": "thinking"})
                rethink = _create_message_with_retry(
                    client,
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=ICPDB_SYSTEM_PROMPT,
                    tools=active_tools,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": rethink.content})
                if rethink.stop_reason == "end_turn":
                    final_text = "".join(
                        b.text for b in rethink.content if hasattr(b, "text")
                    )
                    on_event({"type": "summary", "text": final_text})
                    return final_text
                break

            result = _dispatch(tool_name, tool_input)

            # ── Persist phase outputs ─────────────────────────────────────
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
                    on_event({"type": "phase_saved", "phase": 1})
                on_event({"type": "audit_metrics", **audit_data})

            if tool_name == "notion_update_performer" and "error" not in result and run_id:
                _updated_fields_total += len(result.get("updated_fields", []))

            if tool_name == "draft_outreach_messages" and "error" not in result:
                on_event({"type": "outreach_drafts", "drafts": result.get("drafts", [])})
                if run_id:
                    mem.save_icpdb_phase(run_id, 5, {"drafts_count": result.get("count", 0)})
                    on_event({"type": "phase_saved", "phase": 5})

            result_preview = json.dumps(result, ensure_ascii=False)
            on_event({
                "type":   "tool_result",
                "tool":   tool_name,
                "result": result_preview[:500] + ("…" if len(result_preview) > 500 else ""),
                "ok":     "error" not in result,
            })

            if verbose:
                print(f"   → {result_preview[:300]}")

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     json.dumps(result),
            })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    # Save phase 4 summary if we updated anything
    if _updated_fields_total > 0 and run_id:
        mem.save_icpdb_phase(run_id, 4, {"updated_fields_total": _updated_fields_total})

    return "Agent loop ended unexpectedly."


# ── Public entry point ────────────────────────────────────────────────────────

def run_with_callbacks(
    on_event,
    check_pause,
    get_update_decisions,
    run_mode: str = "full",
    run_id: str | None = None,
    prefs: dict | None = None,
) -> str:
    """Dashboard entry point — streams events via callbacks."""
    if run_id is None:
        run_id = mem.create_icpdb_run(run_mode)

    on_event({"type": "run_id", "run_id": run_id})

    messages = [{"role": "user", "content": audit_prompt(run_mode, prefs=prefs)}]

    on_event({"type": "phase", "phase": 1, "label": "Audit"})

    try:
        result = _loop(
            messages,
            on_event,
            check_pause,
            get_update_decisions,
            run_id,
            verbose=False,
        )
        mem.complete_icpdb_run(run_id)
        on_event({"type": "history_updated"})
        return result
    except Exception as exc:
        mem.fail_icpdb_run(run_id, str(exc))
        on_event({"type": "error", "message": str(exc)})
        raise
