"""
Varekai — Performer Outreach Agent.

Named after Cirque du Soleil's 2002 show ("wherever you go" in Romani).
Runs the quarterly performer outreach cycle: eligibility audit, send queue,
and reply logging — all with human-in-the-loop sending via Instagram.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import anthropic

from .varekai_prompts import SYSTEM_PROMPT, phase_prompt
from .varekai_tools import (
    fetch_performers_with_outreach_fields,
    check_eligibility,
    record_outreach_sent,
    log_outreach_reply,
)
from .kooza_tools import draft_outreach_messages
from . import memory as mem

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

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

# ── Tool dispatch ─────────────────────────────────────────────────────────────

TOOL_FUNCTIONS: dict[str, Any] = {
    "fetch_performers_with_outreach_fields": fetch_performers_with_outreach_fields,
    "check_eligibility":      check_eligibility,
    "draft_outreach_messages": draft_outreach_messages,
    "record_outreach_sent":   record_outreach_sent,
    "log_outreach_reply":     log_outreach_reply,
}


def _dispatch(tool_name: str, tool_input: dict) -> Any:
    fn = TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(**tool_input)
    except Exception as exc:
        return {"error": str(exc)}


# ── Streaming helper ──────────────────────────────────────────────────────────

def _stream_response(client, on_event, **kwargs):
    text_buf = ""
    content = []
    stop_reason = None

    on_event({"type": "thinking"})

    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            etype = getattr(event, "type", "")
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                if block:
                    content.append(block)
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta:
                    dtype = getattr(delta, "type", "")
                    if dtype == "text_delta":
                        text_buf += delta.text
                        on_event({"type": "thinking_delta", "text": delta.text})
                    elif dtype == "thinking_delta":
                        on_event({"type": "thinking_delta", "text": delta.thinking})
            elif etype == "content_block_stop":
                pass
            elif etype == "message_stop":
                stop_reason = getattr(stream.get_final_message(), "stop_reason", None)

    if text_buf:
        on_event({"type": "thinking_done", "text": text_buf})

    final = stream.get_final_message()
    return final


# ── Main agent loop ───────────────────────────────────────────────────────────

def _loop(
    messages: list[dict],
    run_id: str,
    on_event,
    check_pause,
    get_eligibility_decisions,
    get_reply_decisions,
    get_user_input,
    context: list[str] | None = None,
    verbose: bool = False,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    _sent_ids: list[str] = []

    while True:
        response = _stream_response(
            client,
            on_event,
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final = "".join(b.text for b in response.content if hasattr(b, "text"))
            on_event({"type": "summary", "text": final})
            return final

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if not hasattr(block, "type") or block.type != "tool_use":
                continue

            tool_name  = block.name
            tool_input = block.input or {}

            on_event({
                "type":  "tool_call",
                "tool":  tool_name,
                "input": {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
                          for k, v in tool_input.items()},
            })

            # ── Blocking: eligibility / send queue ───────────────────────────
            if tool_name == "propose_outreach_queue":
                stage = tool_input.get("stage", "eligibility")
                performers = tool_input.get("performers", [])
                skipped = tool_input.get("skipped", [])
                on_event({
                    "type":      "outreach_queue",
                    "stage":     stage,
                    "performers": performers,
                    "skipped":   skipped,
                })
                decisions = get_eligibility_decisions(performers)
                # decisions = {confirmed_ids: [...], sent_ids: [...], skipped_ids: [...]}
                if stage == "send_queue":
                    sent_ids = decisions.get("sent_ids", [])
                    _sent_ids.extend(sent_ids)
                    result = {
                        "sent_ids":    sent_ids,
                        "skipped_ids": decisions.get("skipped_ids", []),
                        "sent_count":  len(sent_ids),
                    }
                    mem.save_outreach_phase(run_id, 2, {
                        "sent_count":    len(sent_ids),
                        "skipped_count": len(decisions.get("skipped_ids", [])),
                        "performer_ids_contacted": sent_ids,
                    })
                else:
                    confirmed = decisions.get("confirmed_ids", [pid for p in performers if (pid := p.get("id"))])
                    result = {
                        "confirmed_performers": [p for p in performers if p.get("id") in confirmed],
                        "confirmed_count": len(confirmed),
                    }
                    mem.save_outreach_phase(run_id, 1, {
                        "eligible_count": len(performers),
                        "confirmed_count": len(confirmed),
                    })

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
                on_event({"type": "tool_result", "tool": tool_name,
                          "result": json.dumps(result)[:300], "ok": True})
                continue

            # ── Blocking: reply logging ───────────────────────────────────────
            if tool_name == "propose_reply_logging":
                performers = tool_input.get("performers", [])
                on_event({"type": "outreach_reply_log", "performers": performers})
                decisions = get_reply_decisions(performers)
                # decisions = [{page_id, reply_text, upcoming_shows, status}, ...]
                result = {"logged": len(decisions), "replies": decisions}
                mem.save_outreach_phase(run_id, 3, {"replies_logged": len(decisions)})
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
                on_event({"type": "tool_result", "tool": tool_name,
                          "result": f"Logged {len(decisions)} replies", "ok": True})
                continue

            # ── get_reply_log ─────────────────────────────────────────────────
            if tool_name == "get_reply_log":
                last_run = mem.get_last_outreach_run()
                if last_run and last_run.get("phase2"):
                    ids = last_run["phase2"].get("performer_ids_contacted", [])
                    result = {"performer_ids": ids, "count": len(ids)}
                else:
                    result = {"performer_ids": [], "count": 0,
                              "note": "No previous outreach run found."}
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
                on_event({"type": "tool_result", "tool": tool_name,
                          "result": f"{result['count']} performers from last run", "ok": True})
                continue

            # ── Standard dispatch ─────────────────────────────────────────────
            interject = check_pause()
            if interject:
                messages.append({"role": "user", "content": (
                    f"[User note]: {interject}\nPlease take this into account."
                )})
                on_event({"type": "thinking"})
                break

            result = _dispatch(tool_name, tool_input)
            ok = "error" not in result
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     json.dumps(result),
            })
            on_event({
                "type":   "tool_result",
                "tool":   tool_name,
                "result": str(result)[:300],
                "ok":     ok,
            })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return ""


# ── Public entry point ────────────────────────────────────────────────────────

def run_with_callbacks(
    run_mode: str = "full",
    on_event=None,
    check_pause=None,
    get_eligibility_decisions=None,
    get_reply_decisions=None,
    get_user_input=None,
    context: list[str] | None = None,
) -> str:
    on_event = on_event or (lambda e: None)
    check_pause = check_pause or (lambda: None)
    get_eligibility_decisions = get_eligibility_decisions or (lambda p: {"confirmed_ids": [x.get("id") for x in p]})
    get_reply_decisions = get_reply_decisions or (lambda p: [])
    get_user_input = get_user_input or (lambda: "")

    run_id = mem.create_outreach_run(run_mode)
    on_event({"type": "phase", "phase": 1, "label": "Eligibility Audit"})

    try:
        messages = [{"role": "user", "content": phase_prompt(run_mode, context)}]
        result = _loop(
            messages=messages,
            run_id=run_id,
            on_event=on_event,
            check_pause=check_pause,
            get_eligibility_decisions=get_eligibility_decisions,
            get_reply_decisions=get_reply_decisions,
            get_user_input=get_user_input,
            context=context,
        )
        mem.complete_outreach_run(run_id)
        return result
    except Exception as exc:
        mem.fail_outreach_run(run_id, str(exc))
        on_event({"type": "error", "message": str(exc)})
        raise
