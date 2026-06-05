"""
Alegría — Contortion Space Master Coordinator Agent.

Named after Cirque du Soleil's iconic 1994 show. Alegría coordinates all
Contortion Space agents and serves as the primary conversational interface.

Specialist agents:
  Luzia  — Monthly Performance Review (research, write, publish)
  Kooza  — ICPDB Maintenance (audit, update, deduplicate performer records)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import anthropic

from .tools import web_search
from . import memory as mem

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048

ALEGRIA_SYSTEM_PROMPT = """\
You are Alegría, the master coordinator for Contortion Space (contortion.space) — \
a global publication and performer database covering the contortion training and performance community.

You are named after Cirque du Soleil's iconic 1994 show. Your role is to understand what \
the team needs, answer questions about the platform and the contortion world, \
and coordinate the two specialist agents:

• **Luzia** — the Monthly Performance Review Agent. Luzia researches global contortion \
  performances each month, writes the roundup article, and publishes it to Notion and Webflow. \
  Suggest Luzia when the user wants to create or update a monthly performance review.

• **Kooza** — the ICPDB Agent. Kooza audits and maintains the International Contortion \
  Performer Database (ICPDB) in Notion — updating performer profiles, finding duplicates, \
  and drafting outreach messages. \
  Suggest Kooza when the user wants to update performer records or clean the database.

You have access to web search for quick lookups and can retrieve a status summary of recent runs.

When you recommend launching an agent, call `suggest_agent` with the appropriate parameters — \
this surfaces a launch card in the dashboard so the user can start it with one click.

Be concise, direct, and warm. Write in British English. \
If the user asks a factual question about a contortion performer or show, search the web first.
"""

TOOLS: list[dict] = [
    {
        "name": "web_search",
        "description": "Search the web for current information about contortion, performers, shows, or circus news.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_platform_status",
        "description": (
            "Get a summary of recent agent runs — latest performance review month, "
            "last ICPDB audit date, run counts, etc."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "suggest_agent",
        "description": (
            "Recommend launching a specialist agent for a task. "
            "Sends a suggestion card to the dashboard so the user can launch it with one click."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["luzia", "kooza"],
                    "description": "Which agent to suggest.",
                },
                "reason": {
                    "type": "string",
                    "description": "One sentence explaining why this agent is appropriate.",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Pre-filled launch parameters. "
                        "For Luzia: {\"month_label\": \"June 2026\"}. "
                        "For Kooza: {\"run_mode\": \"full\"} (modes: full, update_only, deduplicate, outreach)."
                    ),
                },
            },
            "required": ["agent", "reason"],
        },
    },
]


def _get_platform_status() -> dict:
    runs = mem.load_all_runs()
    icpdb_runs = mem.load_icpdb_runs()
    return {
        "performance_review": {
            "total_runs": len(runs),
            "latest_month": runs[0].get("month_label") if runs else None,
            "latest_date": (runs[0].get("started_at", "") or "")[:10] if runs else None,
            "latest_status": runs[0].get("status") if runs else None,
        },
        "icpdb": {
            "total_runs": len(icpdb_runs),
            "latest_mode": icpdb_runs[0].get("run_mode") if icpdb_runs else None,
            "latest_date": (icpdb_runs[0].get("started_at", "") or "")[:10] if icpdb_runs else None,
            "latest_status": icpdb_runs[0].get("status") if icpdb_runs else None,
        },
    }


_NOOP_EVENT = lambda event: None
_NOOP_PAUSE = lambda: None


def run_with_callbacks(
    on_event,
    check_pause,
    get_user_message,
    initial_message: str,
) -> None:
    """
    Run the Alegría coordinator as a multi-turn conversation.

    The loop:
    1. Sends the user's message to the model and streams the response.
    2. Handles any tool calls (web_search, get_platform_status, suggest_agent).
    3. After a non-tool response, emits alegria_waiting and blocks on get_user_message().
    4. Repeats until get_user_message() returns None (connection closed).
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages: list[dict] = [{"role": "user", "content": initial_message}]

    while True:
        on_event({"type": "thinking"})

        # Stream response
        full_text = ""
        tool_uses: list[dict] = []
        current_tool: dict | None = None

        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=ALEGRIA_SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                for event in stream:
                    etype = type(event).__name__

                    if etype == "ContentBlockStart":
                        cb = getattr(event, "content_block", None)
                        if cb and getattr(cb, "type", "") == "tool_use":
                            current_tool = {"id": cb.id, "name": cb.name, "input": ""}

                    elif etype == "ContentBlockDelta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue
                        dtype = getattr(delta, "type", "")
                        if dtype == "text_delta":
                            chunk = delta.text or ""
                            full_text += chunk
                            on_event({"type": "alegria_delta", "text": chunk})
                        elif dtype == "input_json_delta" and current_tool is not None:
                            current_tool["input"] += getattr(delta, "partial_json", "")

                    elif etype == "ContentBlockStop":
                        if current_tool is not None:
                            try:
                                current_tool["input"] = json.loads(current_tool["input"] or "{}")
                            except Exception:
                                current_tool["input"] = {}
                            tool_uses.append(current_tool)
                            current_tool = None

        except Exception as exc:
            on_event({"type": "error", "message": str(exc)})
            return

        # Append assistant turn
        assistant_content: list[dict] = []
        if full_text:
            assistant_content.append({"type": "text", "text": full_text})
        for tu in tool_uses:
            assistant_content.append({
                "type": "tool_use",
                "id":   tu["id"],
                "name": tu["name"],
                "input": tu["input"],
            })

        if assistant_content:
            messages.append({"role": "assistant", "content": assistant_content})

        if full_text:
            on_event({"type": "alegria_message", "text": full_text})

        if not tool_uses:
            # Conversation turn complete — wait for next user message
            on_event({"type": "alegria_waiting"})

            # Check for interjections queued up while we were streaming
            injected = check_pause()
            if injected:
                messages.append({"role": "user", "content": injected})
                continue

            user_msg = get_user_message()
            if user_msg is None:
                break
            messages.append({"role": "user", "content": user_msg})
            continue

        # Handle tool calls
        tool_results: list[dict] = []
        for tu in tool_uses:
            name = tu["name"]
            inp  = tu["input"]

            on_event({"type": "tool_call", "tool": name, "input": inp})

            if name == "web_search":
                result = web_search(inp.get("query", ""))
            elif name == "get_platform_status":
                result = _get_platform_status()
            elif name == "suggest_agent":
                on_event({
                    "type":   "agent_suggestion",
                    "agent":  inp.get("agent"),
                    "reason": inp.get("reason", ""),
                    "params": inp.get("params", {}),
                })
                result = {"sent": True}
            else:
                result = {"error": f"Unknown tool: {name}"}

            result_str = json.dumps(result, ensure_ascii=False)
            on_event({
                "type":   "tool_result",
                "tool":   name,
                "result": result_str[:300],
                "ok":     "error" not in result,
            })

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tu["id"],
                "content":     result_str,
            })

        messages.append({"role": "user", "content": tool_results})

        # Non-blocking interjection check between tool rounds
        injected = check_pause()
        if injected:
            messages.append({"role": "user", "content": (
                f"[User interjection]: {injected}\n"
                "Please take this into account and adjust your response."
            )})
