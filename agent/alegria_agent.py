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

from .tools import web_search, notion_search_performer, notion_search_pages, notion_fetch_page
from . import memory as mem
from .config import MODEL

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
You coordinate two specialist AI agents. You can run them directly using run_luzia and \
run_kooza — you do not need to ask the user to go to another panel. Only use suggest_agent \
if the user explicitly asks to open the agent panel themselves.

• **Luzia** (Performance Review Agent) — named after CdS's 2016 Mexico show. \
  Researches global contortion performances for a given month via web search, \
  writes the roundup article, matches performers to the ICPDB, generates imagery, \
  and publishes to Notion and Webflow. Run once per month. \
  Use run_luzia with a month_label. You will be asked to relay performer matching \
  decisions to the user during the run.

• **Kooza** (ICPDB Maintenance Agent) — named after CdS's 2007 show ("treasure" in Sanskrit). \
  Audits performer completeness, fills gaps via web research, detects and resolves \
  duplicate entries, drafts Instagram/email outreach. \
  Use run_kooza with a run_mode: full, update_only, deduplicate, or outreach. \
  You will be asked to relay update/dedup decisions to the user during the run.

• **Varekai** (Performer Outreach Agent) — named after CdS's 2002 show ("wherever you go" \
  in Romani). Runs the quarterly performer outreach cycle: identifies eligible performers \
  (those not contacted in the last 75 days), presents personalised Instagram DM drafts for \
  the editor to send manually, and logs performer replies (including upcoming show info) back \
  to the ICPDB. Replies feed directly into Luzia's monthly research as ✓ Confirmed intelligence. \
  Use run_varekai with a run_mode: full, send_queue (Phase 2 only), or log_replies (Phase 3 only). \
  You will relay eligibility and reply decisions to the user during the run. \
  When contacted by Varekai for context, your saved memories are passed to it automatically.

════════════════════════════════════════
YOUR ROLE
════════════════════════════════════════
You are the editor-in-chief's right hand. Help with:

1. **Content strategy** — which performers to feature, regions to cover, angles to pursue, \
   what stories are emerging in the contortion world
2. **Research** — look up performers in the ICPDB, search the web for current information \
   about shows, performers, competitions, and circus news; read any Notion page by URL or \
   search for pages by keyword using notion_search and notion_fetch_page
3. **Drafting** — social media captions, outreach emails, pitch ideas, interview questions, \
   Instagram Story copy, newsletter blurbs
4. **Run coordination** — running Luzia or Kooza directly when asked, reviewing their \
   outputs, replaying from a specific phase if needed. When the user asks to run an agent, \
   do it — don't ask for confirmation unless something is genuinely ambiguous
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
        "name": "run_luzia",
        "description": (
            "Run the Luzia Performance Review Agent directly. Use this when the user asks you "
            "to run a performance review, write the monthly roundup, or publish an article for "
            "a specific month. Luzia will research performances, match performers to the ICPDB, "
            "generate images, write the article, and publish to Notion and Webflow. "
            "You will be asked to relay any decisions needed (e.g. performer matching) to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month_label": {
                    "type": "string",
                    "description": "Month to run for, e.g. 'May 2025'.",
                },
                "replay_from": {
                    "type": "integer",
                    "description": "Phase to start from (1=Research, 2=Matching, 3=Images, 4=Article, 5=Webflow). Defaults to 1.",
                },
                "replay_run_id": {
                    "type": "string",
                    "description": "Run ID to resume/replay from (optional).",
                },
            },
            "required": ["month_label"],
        },
    },
    {
        "name": "run_kooza",
        "description": (
            "Run the Kooza ICPDB Maintenance Agent directly. Use this when the user asks you "
            "to update the performer database, find duplicates, fill in missing fields, or send "
            "outreach. You will be asked to relay any decisions needed (e.g. approving updates "
            "or resolving duplicates) to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_mode": {
                    "type": "string",
                    "enum": ["full", "update_only", "deduplicate", "outreach"],
                    "description": (
                        "full = audit + research + review + apply + outreach; "
                        "update_only = research + review + apply; "
                        "deduplicate = audit duplicates + resolve; "
                        "outreach = draft outreach messages only."
                    ),
                },
            },
            "required": ["run_mode"],
        },
    },
    {
        "name": "run_varekai",
        "description": (
            "Run the Varekai Performer Outreach Agent directly. Use this when the user asks "
            "to run the quarterly outreach cycle, check who is due for outreach, send DMs, "
            "or log performer replies. Your saved memories are automatically passed to Varekai "
            "as editorial context. You will relay eligibility and reply decisions to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_mode": {
                    "type": "string",
                    "enum": ["full", "send_queue", "log_replies"],
                    "description": (
                        "full = eligibility audit + send queue + reply logging; "
                        "send_queue = Phase 2 (send DMs) only; "
                        "log_replies = Phase 3 (log replies) only."
                    ),
                },
            },
            "required": ["run_mode"],
        },
    },
    {
        "name": "suggest_agent",
        "description": (
            "Show a launch card for a specialist agent WITHOUT running it. Only use this if "
            "the user explicitly wants to go to that agent's panel themselves. "
            "Prefer run_luzia, run_kooza, or run_varekai to actually execute the agent directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["luzia", "kooza", "varekai"],
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
                        "Kooza: {\"run_mode\": \"full\"} — modes: full, update_only, deduplicate, outreach. "
                        "Varekai: {\"run_mode\": \"full\"} — modes: full, send_queue, log_replies."
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
        "name": "notion_search",
        "description": (
            "Search Notion for pages by keyword. Returns a list of matching pages with "
            "their titles, IDs and URLs. Use before notion_fetch_page to find the right page."
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
        "name": "notion_fetch_page",
        "description": (
            "Fetch the full content of a Notion page — title, all properties, and body text. "
            "Accepts a page ID or a notion.so URL. Use to read articles, research notes, "
            "ICPDB records, or any other Notion content for context. "
            "After reading, you can use save_memory to retain key facts for future sessions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id_or_url": {
                    "type": "string",
                    "description": "Notion page ID (UUID) or full notion.so URL",
                },
            },
            "required": ["page_id_or_url"],
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
    from datetime import date as _date
    runs = mem.load_all_runs()
    icpdb_runs = mem.load_icpdb_runs()
    outreach_runs = mem.load_outreach_runs()
    latest_review = next(
        (r for r in runs if r.get("status") == "completed"), None
    ) or (runs[0] if runs else None)
    latest_kooza = next(
        (r for r in icpdb_runs if r.get("status") == "completed"), None
    ) or (icpdb_runs[0] if icpdb_runs else None)
    latest_outreach = mem.get_last_outreach_run()

    outreach_info: dict = {"total_runs": len(outreach_runs)}
    if latest_outreach:
        last_date_str = (latest_outreach.get("completed_at") or latest_outreach.get("created_at", ""))[:10]
        outreach_info["latest_date"] = last_date_str
        outreach_info["latest_status"] = latest_outreach.get("status")
        try:
            last_date = _date.fromisoformat(last_date_str)
            days_since = (_date.today() - last_date).days
            outreach_info["days_since_last"] = days_since
            outreach_info["next_due_in"] = max(0, 90 - days_since)
            outreach_info["due"] = days_since >= 90
        except Exception:
            pass
    else:
        outreach_info["due"] = True

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
        "outreach": outreach_info,
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

    outreach = status["outreach"]
    if outreach.get("latest_date"):
        varekai_line = (
            f"Varekai — last run: {outreach['latest_date']} ({outreach.get('latest_status', '—')}), "
            f"days since: {outreach.get('days_since_last', '?')}, "
            f"next due in: {outreach.get('next_due_in', '?')} days"
            + (" ⚠ OVERDUE" if outreach.get("due") else "")
        )
    else:
        varekai_line = "Varekai — never run (outreach overdue)"

    sections.append(
        f"════════════════════════════════════════\n"
        f"CURRENT PLATFORM STATUS  (today: {today})\n"
        f"════════════════════════════════════════\n"
        f"Luzia — last run: {pr['latest_month'] or 'never'} "
        f"({pr['latest_date'] or '—'}, {pr['latest_status'] or '—'}), "
        f"total reviews: {pr['total_runs']}\n"
        f"Kooza — last run: {icpdb['latest_mode'] or 'never'} mode "
        f"({icpdb['latest_date'] or '—'}, {icpdb['latest_status'] or '—'}), "
        f"total ICPDB runs: {icpdb['total_runs']}\n"
        f"{varekai_line}"
    )

    return "\n\n".join(sections)


def _run_subagent_inline(agent_key: str, inp: dict, on_event, get_user_message) -> dict:
    """Run a specialist agent inline, proxying its events and decisions through chat.

    All blocking decisions arrive via the agent's decide(kind, payload) channel
    and are rendered/parsed by the shared chat handlers in decisions.py.
    """
    from .decisions import chat_decision

    label = {"luzia": "Luzia", "kooza": "Kooza", "varekai": "Varekai"}[agent_key]

    def say(text: str) -> None:
        on_event({"type": "alegria_message", "text": text})

    def ask() -> str:
        on_event({"type": "alegria_waiting"})
        return get_user_message() or ""

    def decide(kind: str, payload: dict):
        return chat_decision(kind, payload, say, ask)

    def sub_on_event(event):
        t = event.get("type", "")
        if t == "phase":
            say(f"**{label} — Phase {event.get('phase')}: {event.get('label', '')}**")
        elif t == "summary":
            say(event.get("text", ""))
        elif t == "error":
            say(f"⚠ {label} error: {event.get('message', '')}")
        elif t in ("tool_call", "tool_result", "thinking", "thinking_delta",
                   "thinking_done", "phase_saved", "run_id", "injected",
                   "audit_metrics", "history_updated"):
            pass  # internal progress noise — not useful as chat bubbles
        else:
            # Pass other events through (images, webflow links, outreach drafts, etc.)
            on_event(event)

    try:
        if agent_key == "luzia":
            from . import luzia_agent
            month_label   = inp.get("month_label", "")
            replay_from   = int(inp.get("replay_from", 1))
            replay_run_id = inp.get("replay_run_id")
            cached_run    = mem.get_run(replay_run_id) if replay_run_id else None
            luzia_agent.run_with_callbacks(
                month_label=month_label,
                on_event=sub_on_event,
                decide=decide,
                replay_from=replay_from,
                cached_run=cached_run,
            )
            return {"status": "completed", "month": month_label}

        if agent_key == "kooza":
            from . import kooza_agent
            run_mode = inp.get("run_mode", "full")
            kooza_agent.run_with_callbacks(
                on_event=sub_on_event,
                decide=decide,
                run_mode=run_mode,
                prefs=mem.get_icpdb_prefs(),
            )
            return {"status": "completed", "run_mode": run_mode}

        if agent_key == "varekai":
            from . import varekai_agent
            run_mode = inp.get("run_mode", "full")
            varekai_agent.run_with_callbacks(
                run_mode=run_mode,
                on_event=sub_on_event,
                decide=decide,
                context=mem.load_alegria_memories(),
            )
            return {"status": "completed", "run_mode": run_mode}

        return {"status": "error", "error": f"Unknown agent: {agent_key}"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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

    # Load persisted history — trim any leading assistant messages (API requires user first)
    raw_history = mem.load_alegria_messages()
    while raw_history and raw_history[0]["role"] != "user":
        raw_history = raw_history[1:]
    history: list[dict] = raw_history
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
                    etype = getattr(event, "type", "")

                    if etype == "content_block_start":
                        cb = getattr(event, "content_block", None)
                        if cb and getattr(cb, "type", "") == "tool_use":
                            current_tool = {"id": cb.id, "name": cb.name, "input": ""}

                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue
                        dtype = getattr(delta, "type", "")
                        if dtype == "text_delta":
                            chunk = getattr(delta, "text", "") or ""
                            full_text += chunk
                            on_event({"type": "alegria_delta", "text": chunk})
                        elif dtype == "input_json_delta" and current_tool is not None:
                            current_tool["input"] += getattr(delta, "partial_json", "")

                    elif etype == "content_block_stop":
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
                # Don't persist the greeting — it's driven by an internal prompt,
                # not a real user message. History must start with a user message.
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
            elif name == "notion_search":
                result = notion_search_pages(inp.get("query", ""))
            elif name == "notion_fetch_page":
                result = notion_fetch_page(inp.get("page_id_or_url", ""))
            elif name == "search_icpdb_performer":
                result = notion_search_performer(inp.get("name", ""))
            elif name == "run_luzia":
                on_event({"type": "alegria_message",
                          "text": f"Starting Luzia for **{inp.get('month_label', '')}**…"})
                result = _run_subagent_inline("luzia", inp, on_event, get_user_message)
            elif name == "run_kooza":
                on_event({"type": "alegria_message",
                          "text": f"Starting Kooza in **{inp.get('run_mode', 'full')}** mode…"})
                result = _run_subagent_inline("kooza", inp, on_event, get_user_message)
            elif name == "run_varekai":
                on_event({"type": "alegria_message",
                          "text": f"Starting Varekai in **{inp.get('run_mode', 'full')}** mode…"})
                result = _run_subagent_inline("varekai", inp, on_event, get_user_message)
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
