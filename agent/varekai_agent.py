"""
Varekai — Performer Outreach Agent.

Named after Cirque du Soleil's 2002 show ("wherever you go" in Romani).
Runs the quarterly performer outreach cycle: eligibility audit, send queue,
and reply logging — all with human-in-the-loop sending via Instagram.
"""

from __future__ import annotations

from .agent_runtime import AgentContext, AgentSpec, run_loop
from .varekai_prompts import SYSTEM_PROMPT, phase_prompt
from .varekai_tools import (
    fetch_performers_with_outreach_fields,
    check_eligibility,
    record_outreach_sent,
    log_outreach_reply,
)
from .kooza_tools import draft_outreach_messages
from . import memory as mem

# ── Tool schemas ──────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "fetch_performers_with_outreach_fields",
        "description": (
            "Fetch all ICPDB performers including outreach tracking fields "
            "(Last Outreach Date, Outreach Response). Use in Phase 1."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_eligibility",
        "description": (
            "Filter a performer list to those due for outreach. Excludes performers "
            "contacted within 75 days or who have Unsubscribed. Returns eligible list, "
            "skipped list with reasons, and a missing_fields warning if tracking fields "
            "are not set up in Notion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "performers": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Performer list from fetch_performers_with_outreach_fields.",
                },
            },
            "required": ["performers"],
        },
    },
    {
        "name": "draft_outreach_messages",
        "description": (
            "Generate personalised Instagram DM drafts for a list of performers. "
            "Returns one draft per performer with the DM text ready to send."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "performers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":        {"type": "string"},
                            "name":      {"type": "string"},
                            "instagram": {"type": "string"},
                        },
                    },
                },
                "upcoming_months": {
                    "type": "string",
                    "description": "E.g. 'July, August, September 2026'",
                },
            },
            "required": ["performers"],
        },
    },
    {
        "name": "propose_outreach_queue",
        "description": (
            "Present the outreach queue to the user. In Phase 1, shows the eligible "
            "performer list for confirmation. In Phase 2, shows DM drafts with "
            "Open Instagram / Mark Sent / Skip controls. Blocks until the user "
            "confirms eligibility or completes the send queue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["eligibility", "send_queue"],
                    "description": "Which stage of the queue to show.",
                },
                "performers": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Eligible performers (eligibility stage) or draft objects (send_queue stage).",
                },
                "skipped": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Skipped performers with reasons (eligibility stage only).",
                },
            },
            "required": ["stage", "performers"],
        },
    },
    {
        "name": "record_outreach_sent",
        "description": "Mark a performer as contacted today in Notion (sets Last Outreach Date = today, Outreach Response = No Response).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Notion page ID of the performer."},
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "get_reply_log",
        "description": "Fetch performers from the most recent outreach run for reply logging.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "propose_reply_logging",
        "description": (
            "Present the reply logging interface to the user — shows each contacted "
            "performer with a reply text box and response status dropdown. Blocks until "
            "the user submits their replies."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "performers": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Performers to log replies for.",
                },
            },
            "required": ["performers"],
        },
    },
    {
        "name": "log_outreach_reply",
        "description": "Save a performer's reply to Notion (Outreach Notes, Upcoming Shows, Outreach Response).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id":       {"type": "string"},
                "reply_text":    {"type": "string", "description": "Full reply text from the performer."},
                "upcoming_shows":{"type": "string", "description": "Extracted upcoming show info."},
                "status":        {"type": "string", "enum": ["Replied", "No Response", "Unsubscribed"]},
            },
            "required": ["page_id"],
        },
    },
]


def get_reply_log() -> dict:
    """Performer IDs contacted in the most recent outreach run."""
    last_run = mem.get_last_outreach_run()
    if last_run and last_run.get("phase2"):
        ids = last_run["phase2"].get("performer_ids_contacted", [])
        return {"performer_ids": ids, "count": len(ids)}
    return {"performer_ids": [], "count": 0, "note": "No previous outreach run found."}


TOOL_FUNCTIONS = {
    "fetch_performers_with_outreach_fields": fetch_performers_with_outreach_fields,
    "check_eligibility":       check_eligibility,
    "draft_outreach_messages": draft_outreach_messages,
    "record_outreach_sent":    record_outreach_sent,
    "log_outreach_reply":      log_outreach_reply,
    "get_reply_log":           get_reply_log,
}

TOOL_PHASE_MAP = {
    "fetch_performers_with_outreach_fields": (1, "Eligibility Audit"),
    "check_eligibility":                     (1, "Eligibility Audit"),
    "draft_outreach_messages":               (2, "Send Queue"),
    "propose_outreach_queue":                (2, "Send Queue"),
    "record_outreach_sent":                  (2, "Send Queue"),
    "get_reply_log":                         (3, "Reply Logging"),
    "propose_reply_logging":                 (3, "Reply Logging"),
    "log_outreach_reply":                    (3, "Reply Logging"),
}


# ── Agent spec ────────────────────────────────────────────────────────────────

def _make_spec(run_id: str) -> AgentSpec:

    def h_propose_queue(tool_input: dict, ctx: AgentContext) -> dict:
        stage = tool_input.get("stage", "eligibility")
        performers = tool_input.get("performers", [])
        skipped = tool_input.get("skipped", [])
        decisions = ctx.decide("outreach_queue", {
            "stage": stage, "performers": performers, "skipped": skipped,
        })

        if stage == "send_queue":
            sent_ids = decisions.get("sent_ids", [])
            mem.save_outreach_phase(run_id, 2, {
                "sent_count":    len(sent_ids),
                "skipped_count": len(decisions.get("skipped_ids", [])),
                "performer_ids_contacted": sent_ids,
            })
            return {
                "sent_ids":    sent_ids,
                "skipped_ids": decisions.get("skipped_ids", []),
                "sent_count":  len(sent_ids),
            }

        confirmed = decisions.get("confirmed_ids",
                                  [p.get("id") for p in performers if p.get("id")])
        mem.save_outreach_phase(run_id, 1, {
            "eligible_count":  len(performers),
            "confirmed_count": len(confirmed),
        })
        return {
            "confirmed_performers": [p for p in performers if p.get("id") in confirmed],
            "confirmed_count":      len(confirmed),
        }

    def h_propose_reply_logging(tool_input: dict, ctx: AgentContext) -> dict:
        performers = tool_input.get("performers", [])
        replies = ctx.decide("outreach_reply_log", {"performers": performers})
        mem.save_outreach_phase(run_id, 3, {"replies_logged": len(replies)})
        return {"logged": len(replies), "replies": replies}

    return AgentSpec(
        name="Varekai",
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
        tool_functions=TOOL_FUNCTIONS,
        tool_phase_map=TOOL_PHASE_MAP,
        blocking_tools={
            "propose_outreach_queue": h_propose_queue,
            "propose_reply_logging":  h_propose_reply_logging,
        },
    )


# ── Public entry point ────────────────────────────────────────────────────────

def run_with_callbacks(
    run_mode: str = "full",
    on_event=None,
    check_pause=None,
    decide=None,
    context: list[str] | None = None,
) -> str:
    """Host entry point — streams events via on_event; decisions via decide(kind, payload)."""
    on_event = on_event or (lambda e: None)

    run_id = mem.create_outreach_run(run_mode)
    on_event({"type": "run_id", "run_id": run_id})
    on_event({"type": "phase", "phase": 1, "label": "Eligibility Audit"})

    ctx = AgentContext(on_event=on_event, check_pause=check_pause, decide=decide)
    messages = [{"role": "user", "content": phase_prompt(run_mode, context)}]

    try:
        result = run_loop(_make_spec(run_id), messages, ctx)
        mem.complete_outreach_run(run_id)
        return result
    except Exception as exc:
        mem.fail_outreach_run(run_id, str(exc))
        on_event({"type": "error", "message": str(exc)})
        raise
