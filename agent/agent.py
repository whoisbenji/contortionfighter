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
        "name": "notion_create_article_page",
        "description": (
            "Create the finished monthly article as a new page in the 'Monthly performance posts' "
            "Notion database. Links the article to matched ICPDB performer pages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month_label": {"type": "string", "description": "E.g. 'June 2026'"},
                "article_body": {"type": "string", "description": "Full article in Markdown."},
                "performer_page_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Notion page IDs for performers mentioned in the article.",
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
            "Generate the Instagram Story (1080×1920) and article header (1500×844) images "
            "using performer photos from the Notion ICPDB. Uploads the header to Webflow Assets. "
            "Call this in Phase 3b, after performer matching and before creating the Webflow draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month_label": {"type": "string", "description": "E.g. 'June 2026'"},
                "performer_page_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Notion page IDs for the matched performers (up to 16 used).",
                },
            },
            "required": ["month_label", "performer_page_ids"],
        },
    },
    {
        "name": "webflow_create_blog_draft",
        "description": (
            "Create a draft Blog Post in Webflow CMS with the article content. "
            "The post is saved as isDraft=true so it must be reviewed before publishing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "slug": {"type": "string", "description": "URL-safe slug, e.g. 'june-2026-contortion-roundup'"},
                "description": {"type": "string", "description": "One-sentence meta description."},
                "body_html": {"type": "string", "description": "Article body as HTML (no inline styles)."},
                "featured_performer_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Webflow item IDs for the Featured Performers multi-reference field.",
                },
                "hero_image_asset_id": {
                    "type": "string",
                    "description": "Webflow asset ID for the hero/header image (from generate_images).",
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


# ── Agent loop ────────────────────────────────────────────────────────────────

def run(month_label: str, verbose: bool = True) -> str:
    """
    Run the full four-phase performance review agent for the given month.
    Returns the final summary text from the model.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages: list[dict] = [{"role": "user", "content": phase_prompt(month_label)}]

    if verbose:
        print(f"\n🤸 Starting performance review agent for {month_label}\n{'─'*60}")

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Extract the final text block
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            if verbose:
                print("\n✅ Agent complete.\n")
                print(final_text)
            return final_text

        if response.stop_reason != "tool_use":
            break

        # Process all tool calls in this turn
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_name = block.name
            tool_input = block.input

            if verbose:
                print(f"\n🔧 Tool: {tool_name}")
                # Show a brief preview of the input
                preview = json.dumps(tool_input, ensure_ascii=False)
                print(f"   Input: {preview[:200]}{'…' if len(preview) > 200 else ''}")

            result = _dispatch(tool_name, tool_input)

            if verbose:
                preview = json.dumps(result, ensure_ascii=False)
                print(f"   Result: {preview[:300]}{'…' if len(preview) > 300 else ''}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_results})

    return "Agent loop ended unexpectedly."
