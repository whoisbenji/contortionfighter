"""
Core agent loop. Uses the Anthropic SDK with tool_use to drive the
four-phase performance review workflow.
"""

from __future__ import annotations
import json
import os
from typing import Any

import anthropic

from .prompts import SYSTEM_PROMPT, phase_prompt
from .tools import (
    web_search,
    notion_create_research_page,
    notion_create_article_page,
    notion_search_performer,
    notion_list_performers_in_icpdb,
    notion_create_performer,
    notion_list_shows,
    notion_search_show,
    webflow_find_performers,
    webflow_create_blog_draft,
    generate_images,
)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

# ── Tool schema definitions passed to the API ────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "web_search",
        "description": (
            "Search the web for information about contortion performances, circus shows, "
            "and performer schedules. Use multiple targeted queries to gather comprehensive data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query string."},
                "max_results": {"type": "integer", "default": 8, "description": "Number of results to return (max 10)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "notion_create_research_page",
        "description": (
            "Save raw research notes as a new page in the Notion 'Monthly research' database. "
            "Call this once at the end of Phase 1."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month_label": {"type": "string", "description": "E.g. 'June 2026'"},
                "content_markdown": {"type": "string", "description": "Full research notes in Markdown."},
            },
            "required": ["month_label", "content_markdown"],
        },
    },
    {
        "name": "notion_list_performers_in_icpdb",
        "description": (
            "Return all active performers in the International Contortion Performers Database "
            "(ICPDB) with their Notion page IDs and Instagram handles. Use this for Phase 2 matching."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200, "description": "Maximum performers to return."},
            },
            "required": [],
        },
    },
    {
        "name": "notion_search_performer",
        "description": "Search the ICPDB for a specific performer by name. Use when bulk list doesn't find a match.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Performer name to search for."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "request_performer_review",
        "description": (
            "After completing ICPDB matching, call this with any performers found in research "
            "who are NOT in the ICPDB. The user will review each one and decide to Add or Skip. "
            "Returns a decisions list. Only call if there are unmatched performers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "unmatched_performers": {
                    "type": "array",
                    "description": "Performers not found in the ICPDB.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "instagram": {"type": "string", "description": "Handle without @, if known."},
                            "context": {"type": "string", "description": "Where they appeared (show/venue)."},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["unmatched_performers"],
        },
    },
    {
        "name": "notion_create_performer",
        "description": "Create a new performer entry in the ICPDB. Only call after user approved adding them via request_performer_review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Performer's full name."},
                "instagram": {"type": "string", "description": "Instagram handle (without @)."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "notion_list_shows",
        "description": "Return shows from the Shows database. Use in Phase 2 to match shows mentioned in research.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },
    {
        "name": "notion_search_show",
        "description": "Search the Shows database for a specific show by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Show name to search for."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "notion_create_article_page",
        "description": (
            "Create the finished monthly article as a new page in the 'Monthly performance posts' "
            "Notion database. Links the article to matched ICPDB performer pages and show pages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month_label": {"type": "string", "description": "E.g. 'June 2026'"},
                "article_body": {"type": "string", "description": "Full article in Markdown."},
                "performer_page_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Notion page IDs for performers mentioned in the article.",
                },
                "show_page_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Notion page IDs for shows mentioned in the article.",
                },
            },
            "required": ["month_label", "article_body", "performer_page_ids"],
        },
    },
    {
        "name": "webflow_find_performers",
        "description": (
            "Find Webflow CMS item IDs for a list of performer names. "
            "Use in Phase 4 to populate the featured-performers field."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of performer names to look up.",
                },
            },
            "required": ["names"],
        },
    },
    {
        "name": "generate_images",
        "description": (
            "Generate the Instagram Story (1080x1920) and article header (1500x844) images "
            "using performer photos from the Notion ICPDB. Uploads the header to Webflow Assets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month_label": {"type": "string", "description": "E.g. 'June 2026'"},
                "performer_page_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Notion page IDs for matched performers (up to 16).",
                },
            },
            "required": ["month_label", "performer_page_ids"],
        },
    },
    {
        "name": "webflow_create_blog_draft",
        "description": (
            "Create a draft Blog Post in Webflow CMS. Saved as isDraft=true for review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "slug": {"type": "string", "description": "URL-safe slug."},
                "description": {"type": "string", "description": "One-sentence meta description."},
                "body_html": {"type": "string", "description": "Article body as HTML."},
                "featured_performer_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Webflow item IDs for Featured Performers.",
                },
                "hero_image_asset_id": {
                    "type": "string",
                    "description": "Webflow asset ID for the hero image.",
                },
            },
            "required": ["title", "slug", "description", "body_html"],
        },
    },
]

# ── Tool dispatcher ───────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "web_search": web_search,
    "notion_create_research_page": notion_create_research_page,
    "notion_list_performers_in_icpdb": notion_list_performers_in_icpdb,
    "notion_search_performer": notion_search_performer,
    "notion_create_performer": notion_create_performer,
    "notion_list_shows": notion_list_shows,
    "notion_search_show": notion_search_show,
    "notion_create_article_page": notion_create_article_page,
    "generate_images": generate_images,
    "webflow_find_performers": webflow_find_performers,
    "webflow_create_blog_draft": webflow_create_blog_draft,
}


def _dispatch(tool_name: str, tool_input: dict) -> Any:
    fn = TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(**tool_input)
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase detection ───────────────────────────────────────────────────────────

TOOL_PHASE_MAP = {
    "web_search":                      (1, "Research"),
    "notion_create_research_page":     (1, "Research"),
    "notion_list_performers_in_icpdb": (2, "Performer Matching"),
    "notion_search_performer":         (2, "Performer Matching"),
    "request_performer_review":        (2, "Performer Matching"),
    "notion_create_performer":         (2, "Performer Matching"),
    "notion_list_shows":               (2, "Performer Matching"),
    "notion_search_show":              (2, "Performer Matching"),
    "generate_images":                 (3, "Image Generation"),
    "notion_create_article_page":      (4, "Writing Article"),
    "webflow_find_performers":         (5, "Publishing to Webflow"),
    "webflow_create_blog_draft":       (5, "Publishing to Webflow"),
}

_NOOP_EVENT  = lambda event: None
_NOOP_PAUSE  = lambda: None
_NOOP_REVIEW = lambda performers: {"decisions": [{"name": p["name"], "action": "skip"} for p in performers]}


# ── Core loop (shared by CLI and dashboard) ───────────────────────────────────

def _loop(
    month_label: str,
    messages: list[dict],
    on_event,
    check_pause,
    get_performer_review,
    verbose: bool,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    current_phase = 0

    while True:
        on_event({"type": "thinking"})

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            on_event({"type": "summary", "text": final_text})
            if verbose:
                print("\n✅ Agent complete.\n")
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

            # Emit phase change if needed
            phase_num, phase_label = TOOL_PHASE_MAP.get(tool_name, (current_phase, "Working"))
            if phase_num != current_phase:
                current_phase = phase_num
                on_event({"type": "phase", "phase": phase_num, "label": phase_label})

            # Emit tool_call event
            on_event({
                "type":  "tool_call",
                "tool":  tool_name,
                "input": {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
                          for k, v in tool_input.items()},
            })

            if verbose:
                print(f"\n🔧 {tool_name}: {json.dumps(tool_input)[:200]}")

            # ── Special: performer review blocks until user responds ──────
            if tool_name == "request_performer_review":
                performers = tool_input.get("unmatched_performers", [])
                on_event({"type": "performer_review", "performers": performers})
                result = get_performer_review(performers)  # blocks
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
                on_event({
                    "type":   "tool_result",
                    "tool":   tool_name,
                    "result": json.dumps(result)[:500],
                    "ok":     True,
                })
                continue

            # Check for pause / interject before running the tool
            interject = check_pause()
            if interject:
                messages.append({"role": "user", "content": (
                    f"[User interjection]: {interject}\n"
                    "Please take this into account and adjust your next action accordingly."
                )})
                on_event({"type": "thinking"})
                rethink = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
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

    return "Agent loop ended unexpectedly."


# ── Public entry points ───────────────────────────────────────────────────────

def run(month_label: str, verbose: bool = True) -> str:
    """CLI entry point — prints progress, no WebSocket."""
    messages = [{"role": "user", "content": phase_prompt(month_label)}]
    if verbose:
        print(f"\n🤸 Starting performance review agent for {month_label}\n{'─'*60}")
    return _loop(month_label, messages, _NOOP_EVENT, _NOOP_PAUSE, _NOOP_REVIEW, verbose)


def run_with_callbacks(
    month_label: str,
    on_event,
    check_pause,
    get_performer_review,
) -> str:
    """Dashboard entry point — streams events via callbacks."""
    messages = [{"role": "user", "content": phase_prompt(month_label)}]
    on_event({"type": "phase", "phase": 1, "label": "Research"})
    return _loop(month_label, messages, on_event, check_pause, get_performer_review, verbose=False)
