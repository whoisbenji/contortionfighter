"""
Alegría — Contortion Space Master Coordinator and AI Assistant.

Named after Cirque du Soleil's iconic 1994 show. Alegría is the primary
operational intelligence for the Contortion Space publication — a persistent
chatbot with memory that helps run the business day to day.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import anthropic

from .tools import web_search, notion_search_performer
from . import memory as mem

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

_BASE_SYSTEM_PROMPT = """\
You are Alegría, the dedicated AI assistant for Contortion Space (contortion.space) — \
a specialist global publication covering the contortion training and performance community. \
You are named after Cirque du Soleil's legendary 1994 show.

════════════════════════════════════════
ABOUT CONTORTION SPACE
════════════════════════════════════════
Contortion Space is the definitive English-language resource for the global contortion \
community — coaches, students, working performers, circus enthusiasts, and industry \
professionals worldwide. Core outputs:

• Monthly global performance roundup articles — tracking contortionists performing \
  worldwide each month, published to the website via Webflow and archived in Notion
• The ICPDB (International Contortion Performer Database) — a Notion-based registry \
  of active performers with Instagram handles, nationalities, show affiliations, \
  training backgrounds, and contact details
• Profiles, interviews, and training resources (planned)
• Competition coverage: Monte Carlo, Wuqiao, Saratov "Princess of Circus", \
  Moscow "Idol", Cirque de Demain

════════════════════════════════════════
YOUR SPECIALIST AGENTS
════════════════════════════════════════
You coordinate two specialist AI agents. When a task calls for one, call suggest_agent \
and a launch card will appear in the dashboard.

• **Luzia** (Performance Review Agent) — named after CdS's 2016 Mexico show. \
  Researches global contortion performances for a given month via web search, \
  writes the roundup article, matches performers to the ICPDB, generates imagery, \
  and publishes to Notion and Webflow. Run once per month.
  Run modes: fresh run or replay from any phase.

• **Kooza** (ICPDB Maintenance Agent) — named after CdS's 2007 show ("treasure" in Sanskrit). \
  Audits performer completeness, fills gaps via web research, detects and resolves \
  duplicate entries, drafts Instagram/email outreach. Run modes: full, update_only, \
  deduplicate, outreach.

════════════════════════════════════════
YOUR ROLE
════════════════════════════════════════
You are the editor-in-chief's right hand. Help with:

1. **Content strategy** — which performers to feature, regions to cover, angles to pursue, \
   what stories are emerging in the contortion world
2. **Research** — look up performers in the ICPDB, search the web for current information \
   about shows, performers, competitions, and circus news
3. **Drafting** — social media captions, outreach emails, pitch ideas, interview questions, \
   Instagram Story copy, newsletter blurbs
4. **Run coordination** — advising when to run Luzia or Kooza, reviewing their outputs, \
   suggesting replay from a specific phase if needed
5. **Memory** — when the user shares important context (a focus area, a planned feature, \
   a preference, a decision made), use save_memory to retain it for future conversations
6. **Platform knowledge** — answer questions about how the platform works, what's been done, \
   what's coming up

════════════════════════════════════════
PERSONALITY & TONE
════════════════════════════════════════
• Warm, authoritative, and direct — like a knowledgeable senior editor who's done the research
• Genuinely enthusiastic about contortion as an art form — you find it beautiful and fascinating
• You have opinions: "I think the Southeast Asia section has been undercovered lately" \
  or "This is one of the strongest months we've had for Russian state circus coverage"
• Concise — get to the point. One clear recommendation is better than a list of options
• British English throughout
• Remember context from previous conversations and refer back to it naturally — \
  "You mentioned last time you wanted to focus on Mongolian performers — is that still the plan?"
• You can be honest when something is outside your knowledge: \
  "I'd need to search for that — let me look it up"

════════════════════════════════════════
KNOWLEDGE BASE
════════════════════════════════════════
You know the contortion world deeply:

Major circuits & companies:
• Cirque du Soleil (Las Vegas residents, touring, arena, cruise ship)
• Chinese state circus and acrobatic troupes (Wuqiao, Shanghai, Beijing)
• Mongolian national circus (Ulaanbaatar) and diaspora performers
• Russian state circuses (Bolshoi Circus, touring productions)
• European new circus (Cirque de Demain, Festival Mondial du Cirque de Demain)
• Southeast Asian touring troupes (Phare Circus Cambodia, etc.)
• Independent cabaret performers (Cirque le Soir London, House of Yes NYC, etc.)

Competitions and festivals:
• Festival International du Cirque de Monte-Carlo (January, Monte Carlo)
• Wuqiao International Acrobatics Art Festival (China, autumn)
• "Princess of Circus" — Saratov International Circus Festival (Russia)
• "Idol" — Moscow International Circus Festival
• Festival Mondial du Cirque de Demain (Paris, January/February)

Instagram is the primary self-promotion channel for contortion performers.
Key sources: kassir.kg, pharecircus.org, BroadwayWorld, ticketon.kz, karabas.com.

Technical vocabulary: kauchuk (Russian for contortion), uran nugaralt (Mongolian), 柔术 (Chinese)

════════════════════════════════════════
ACCURACY RULES
════════════════════════════════════════
• Never invent performer names, show assignments, venues, or dates
• If asked about a specific performer, use search_icpdb_performer to check what we have
• Flag when information may be outdated (training knowledge cutoff: August 2025)
• Use web_search when you need current information
• Say "I don't know" rather than guessing — then offer to search

════════════════════════════════════════
SAVE MEMORY GUIDANCE
════════════════════════════════════════
Save a memory when the user:
• States a priority or focus area ("we want to cover more Southeast Asian performers")
• Makes a decision ("we're going to run Luzia on the 1st of each month")
• Shares preferences about how things should work
• Mentions something important about the business or their plans
• Tells you something about themselves or their role

Keep memory notes concise (one sentence). Don't save routine conversation.
"""


TOOLS: list[dict] = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current information about contortion performers, shows, "
            "competitions, or circus news. Use when you need facts you're not certain about."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_platform_status",
        "description": (
            "Get a live summary of recent Luzia and Kooza agent runs — "
            "latest month covered, last ICPDB audit, run counts and statuses."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "suggest_agent",
        "description": (
            "Recommend launching a specialist agent. Sends a launch card to the dashboard "
            "so the user can start it with one click. Call when the user's request clearly "
            "calls for Luzia (performance review) or Kooza (ICPDB maintenance)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["luzia", "kooza"],
                    "description": "Which agent to suggest",
                },
                "reason": {
                    "type": "string",
                    "description": "One sentence explaining why this agent is appropriate.",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Pre-filled launch parameters. "
                        "Luzia: {\"month_label\": \"June 2026\"}. "
                        "Kooza: {\"run_mode\": \"full\"} — modes: full, update_only, deduplicate, outreach."
                    ),
                },
            },
            "required": ["agent", "reason"],
        },
    },
    {
        "name": "search_icpdb_performer",
        "description": (
            "Search the ICPDB (Notion performer database) for a specific performer by name. "
            "Use when the user asks about a particular performer or you need to check whether "
            "someone is in the database."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Performer name to search for"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important fact, preference, or decision to long-term memory. "
            "This note will be included in future conversations. "
            "Use for things the user would expect you to remember next time — "
            "priorities, decisions, focus areas, preferences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "The memory to save (one concise sentence).",
                },
            },
            "required": ["note"],
        },
    },
]


def _get_platform_status() -> dict:
    runs = mem.load_all_runs()
    icpdb_runs = mem.load_icpdb_runs()
    latest_review = next(
        (r for r in runs if r.get("status") == "completed"), None
    ) or (runs[0] if runs else None)
    latest_kooza = next(
        (r for r in icpdb_runs if r.get("status") == "completed"), None
    ) or (icpdb_runs[0] if icpdb_runs else None)
    return {
        "performance_review": {
            "total_runs": len(runs),
            "latest_month": latest_review.get("month_label") if latest_review else None,
            "latest_date": (latest_review.get("completed_at") or latest_review.get("started_at", ""))[:10] if latest_review else None,
            "latest_status": latest_review.get("status") if latest_review else None,
        },
        "icpdb": {
            "total_runs": len(icpdb_runs),
            "latest_mode": latest_kooza.get("run_mode") if latest_kooza else None,
            "latest_date": (latest_kooza.get("completed_at") or latest_kooza.get("started_at", ""))[:10] if latest_kooza else None,
            "latest_status": latest_kooza.get("status") if latest_kooza else None,
        },
    }


def _build_system_prompt() -> str:
    """Build a dynamic system prompt that includes memories and current platform status."""
    today = datetime.now().strftime("%A, %d %B %Y")
    memories = mem.load_alegria_memories()
    status = _get_platform_status()
    pr = status["performance_review"]
    icpdb = status["icpdb"]

    sections = [_BASE_SYSTEM_PROMPT]

    if memories:
        sections.append(
            "════════════════════════════════════════\n"
            "SAVED MEMORIES (retained from previous conversations)\n"
            "════════════════════════════════════════\n"
            + "\n".join(f"• {m}" for m in memories)
        )

    sections.append(
        f"════════════════════════════════════════\n"
        f"CURRENT PLATFORM STATUS  (today: {today})\n"
        f"════════════════════════════════════════\n"
        f"Luzia — last run: {pr['latest_month'] or 'never'} "
        f"({pr['latest_date'] or '—'}, {pr['latest_status'] or '—'}), "
        f"total reviews: {pr['total_runs']}\n"
        f"Kooza — last run: {icpdb['latest_mode'] or 'never'} mode "
        f"({icpdb['latest_date'] or '—'}, {icpdb['latest_status'] or '—'}), "
        f"total ICPDB runs: {icpdb['total_runs']}"
    )

    return "\n\n".join(sections)


_NOOP_EVENT = lambda event: None
_NOOP_PAUSE = lambda: None


def run_with_callbacks(
    on_event,
    check_pause,
    get_user_message,
    fresh: bool = False,
) -> None:
    """
    Run the Alegría chatbot. Persists conversation history across sessions.

    Args:
        fresh: If True, clear history and start a new conversation.
    """
    if fresh:
        mem.clear_alegria_history()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Load persisted history
    history = mem.load_alegria_messages()
    messages: list[dict] = list(history)

    is_first_turn = len(messages) == 0

    if is_first_turn:
        # First ever conversation — send greeting
        greet_msg = (
            "Hello! Give me a friendly two-sentence welcome, introduce yourself briefly, "
            "and let me know what you can help with. Be warm and concise."
        )
        messages.append({"role": "user", "content": greet_msg})
    else:
        # Resuming — wait for user's first message
        on_event({"type": "alegria_waiting"})
        first_msg = get_user_message()
        if first_msg is None:
            return
        messages.append({"role": "user", "content": first_msg})

    while True:
        on_event({"type": "thinking"})

        system_prompt = _build_system_prompt()

        full_text = ""
        tool_uses: list[dict] = []
        current_tool: dict | None = None

        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
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

        # Build assistant turn for messages list
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
            # Persist this exchange (text only) and wait for next user message
            if is_first_turn and full_text:
                # Don't persist the internal greeting prompt — just the assistant reply
                _persist_exchange([], full_text, history)
                is_first_turn = False
            elif full_text and len(messages) >= 2:
                last_user = messages[-2] if messages[-2]["role"] == "user" else None
                user_text = last_user["content"] if last_user and isinstance(last_user["content"], str) else ""
                _persist_exchange(history, full_text, history, user_text=user_text)

            on_event({"type": "alegria_waiting"})

            injected = check_pause()
            if injected:
                messages.append({"role": "user", "content": injected})
                continue

            user_msg = get_user_message()
            if user_msg is None:
                break

            messages.append({"role": "user", "content": user_msg})
            continue

        # Handle tools
        tool_results: list[dict] = []
        for tu in tool_uses:
            name = tu["name"]
            inp  = tu["input"]

            on_event({"type": "tool_call", "tool": name,
                      "input": {k: (v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v)
                                for k, v in inp.items()}})

            if name == "web_search":
                result = web_search(inp.get("query", ""))
            elif name == "get_platform_status":
                result = _get_platform_status()
            elif name == "search_icpdb_performer":
                result = notion_search_performer(inp.get("name", ""))
            elif name == "suggest_agent":
                on_event({
                    "type":   "agent_suggestion",
                    "agent":  inp.get("agent"),
                    "reason": inp.get("reason", ""),
                    "params": inp.get("params", {}),
                })
                result = {"sent": True}
            elif name == "save_memory":
                note = inp.get("note", "").strip()
                if note:
                    mem.save_alegria_memory(note)
                    on_event({"type": "alegria_memory_saved", "note": note})
                result = {"saved": True, "note": note}
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

        injected = check_pause()
        if injected:
            messages.append({"role": "user", "content": (
                f"[User note]: {injected}\n"
                "Take this into account in your response."
            )})


def _persist_exchange(
    existing_history: list[dict],
    assistant_text: str,
    history_ref: list[dict],
    user_text: str = "",
) -> None:
    """Append the latest exchange to persisted history."""
    updated = list(existing_history)
    if user_text:
        updated.append({"role": "user", "content": user_text})
    if assistant_text:
        updated.append({"role": "assistant", "content": assistant_text})
    mem.save_alegria_messages(updated)
    # Update in-place so subsequent saves accumulate correctly
    history_ref.clear()
    history_ref.extend(updated)
