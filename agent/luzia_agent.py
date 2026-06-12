"""
Core agent loop. Uses the Anthropic SDK with tool_use to drive the
four-phase performance review workflow.
"""

from __future__ import annotations

from .agent_runtime import AgentContext, AgentSpec, run_loop
from .luzia_prompts import SYSTEM_PROMPT, phase_prompt, replay_prompt
from .tools import (
    web_search,
    notion_create_research_page,
    notion_create_article_page,
    notion_search_performer,
    notion_list_performers_in_icpdb,
    notion_create_performer,
    load_outreach_replies,
    notion_list_shows,
    notion_search_show,
    webflow_find_performers,
    webflow_create_blog_draft,
    generate_images,
    set_performer_photo,
)
from .compositor import check_performer_photos
from . import memory as mem

# ── Tool schema definitions passed to the API ────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "load_outreach_replies",
        "description": (
            "Check whether any performers have recently reported upcoming shows via "
            "direct outreach replies logged by Varekai. Returns performer names, Instagram "
            "handles, and their upcoming show info. Treat results as ✓ Confirmed. "
            "Call this early in Phase 1 before web searches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "months_back": {
                    "type": "integer",
                    "default": 4,
                    "description": "How many months back to look for logged replies.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "ask_about_existing_research",
        "description": (
            "Ask the user whether they want to use previously saved research instead of "
            "running new web searches. Call this FIRST before any Phase 1 work. "
            "Returns the user's text response."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "load_existing_research",
        "description": (
            "Load the saved research content from a previous run. "
            "Use the run_id returned from ask_about_existing_research. "
            "Returns the full research markdown so you can proceed directly to Phase 2."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID to load research from."},
            },
            "required": ["run_id"],
        },
    },
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
        "name": "review_matched_performers",
        "description": (
            "Show the user the full list of performers matched for this month and ask "
            "whether any are missing. The user can approve the list, name additional "
            "performers to research, or ask you to double-check a region. "
            "Returns the user's response text. Call this after processing performer "
            "review decisions and before proceeding to Phase 2b."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "matched_performers": {
                    "type": "array",
                    "description": "All performers matched so far.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":      {"type": "string"},
                            "instagram": {"type": "string", "description": "Handle without @"},
                            "context":   {"type": "string", "description": "Show / venue / region"},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["matched_performers"],
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
            "Use in Phase 5 to populate the featured-performers field."
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

def load_existing_research(run_id: str) -> dict:
    """Load research content from a past run."""
    run = mem.get_run(run_id)
    if not run:
        return {"error": f"Run '{run_id}' not found."}
    research = run.get("research")
    if not research:
        return {"error": f"Run '{run_id}' has no saved research."}
    return {
        "run_id":           run_id,
        "month_label":      run.get("month_label", ""),
        "notion_url":       research.get("notion_url", ""),
        "content_markdown": research.get("content_markdown", ""),
    }


TOOL_FUNCTIONS = {
    "load_outreach_replies":           load_outreach_replies,
    "load_existing_research":         load_existing_research,
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


# ── Phase detection ───────────────────────────────────────────────────────────

TOOL_PHASE_MAP = {
    "load_outreach_replies":           (1, "Research"),
    "ask_about_existing_research":     (1, "Research"),
    "load_existing_research":          (1, "Research"),
    "web_search":                      (1, "Research"),
    "notion_create_research_page":     (1, "Research"),
    "notion_list_performers_in_icpdb": (2, "Performer Matching"),
    "notion_search_performer":         (2, "Performer Matching"),
    "request_performer_review":        (2, "Performer Matching"),
    "review_matched_performers":       (2, "Performer Matching"),
    "notion_create_performer":         (2, "Performer Matching"),
    "notion_list_shows":               (2, "Performer Matching"),
    "notion_search_show":              (2, "Performer Matching"),
    "generate_images":                 (3, "Image Generation"),
    "notion_create_article_page":      (4, "Writing Article"),
    "webflow_find_performers":         (5, "Publishing to Webflow"),
    "webflow_create_blog_draft":       (5, "Publishing to Webflow"),
}

# ── Phase output extraction ───────────────────────────────────────────────────

def _extract_phase_output(tool_name: str, tool_input: dict, result: dict) -> tuple[int, dict] | None:
    """Return (phase, data) if this tool result should be persisted, else None."""
    if tool_name == "notion_create_research_page" and "error" not in result:
        return 1, {
            "notion_page_id":    result.get("page_id"),
            "notion_url":        result.get("url"),
            "content_markdown":  tool_input.get("content_markdown", ""),
        }
    if tool_name == "generate_images" and "error" not in result:
        return 3, {
            "story_path":        result.get("story_path"),
            "header_path":       result.get("header_path"),
            "webflow_asset_id":  result.get("webflow_asset_id"),
        }
    if tool_name == "notion_create_article_page" and "error" not in result:
        return 4, {
            "notion_page_id":  result.get("page_id"),
            "notion_url":      result.get("url"),
            "body_markdown":   tool_input.get("article_body", ""),
            "performer_ids":   tool_input.get("performer_page_ids", []),
            "show_ids":        tool_input.get("show_page_ids", []),
        }
    if tool_name == "webflow_create_blog_draft" and "error" not in result:
        return 5, {
            "item_id":      result.get("item_id"),
            "draft_url":    result.get("draft_url"),
            "editor_url":   result.get("webflow_editor_url"),
        }
    return None


# ── Agent spec ────────────────────────────────────────────────────────────────

def _make_spec(run_id: str | None) -> AgentSpec:
    matched_names: list[str] = []

    def h_ask_existing(tool_input: dict, ctx: AgentContext) -> dict:
        past_runs = [
            {
                "run_id":      r["id"],
                "month_label": r.get("month_label", ""),
                "created_at":  r.get("created_at", "")[:10],
                "notion_url":  r.get("research", {}).get("notion_url", "") if r.get("research") else "",
            }
            for r in mem.load_all_runs()
            if r.get("research") and r.get("status") == "completed"
        ]
        answer = ctx.decide("research_question", {"past_runs": past_runs})
        return {"answer": answer, "past_runs": past_runs}

    def h_performer_review(tool_input: dict, ctx: AgentContext) -> dict:
        performers = tool_input.get("unmatched_performers", [])
        return ctx.decide("performer_review", {"performers": performers})

    def h_list_review(tool_input: dict, ctx: AgentContext) -> dict:
        performers = tool_input.get("matched_performers", [])
        response = ctx.decide("performer_list_review", {"performers": performers})
        return {"user_response": response or "ok"}

    def pre_tool(tool_name: str, tool_input: dict, ctx: AgentContext) -> None:
        # Photo check before image generation — collect missing photo URLs
        if tool_name != "generate_images":
            return
        performers = check_performer_photos(tool_input.get("performer_page_ids", []))
        missing_count = sum(1 for p in performers if not p["has_photo"])
        photo_urls = ctx.decide("photo_check", {
            "performers": performers, "missing_count": missing_count,
        })
        for pid, url in (photo_urls or {}).items():
            if url and url.strip():
                try:
                    set_performer_photo(pid, url.strip())
                    ctx.on_event({"type": "tool_result", "tool": "set_performer_photo",
                                  "result": f"Photo saved for {pid}", "ok": True})
                except Exception as exc:
                    ctx.on_event({"type": "tool_result", "tool": "set_performer_photo",
                                  "result": f"Failed to save photo: {exc}", "ok": False})

    def after_tool(tool_name: str, tool_input: dict, result: dict, ctx: AgentContext):
        phase_out = _extract_phase_output(tool_name, tool_input, result)
        if phase_out and run_id:
            phase_num, phase_data = phase_out
            mem.save_phase(run_id, phase_num, phase_data)
            ctx.on_event({"type": "phase_saved", "phase": phase_num})

        if tool_name == "notion_create_performer" and "error" not in result:
            matched_names.append(result.get("name", ""))
        if tool_name == "notion_create_article_page" and "error" not in result and run_id:
            mem.save_phase(run_id, 2, {
                "performer_page_ids": tool_input.get("performer_page_ids", []),
                "show_page_ids":      tool_input.get("show_page_ids", []),
                "performer_names":    matched_names,
            })
        return None

    return AgentSpec(
        name="Luzia",
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
        tool_functions=TOOL_FUNCTIONS,
        tool_phase_map=TOOL_PHASE_MAP,
        blocking_tools={
            "ask_about_existing_research": h_ask_existing,
            "request_performer_review":    h_performer_review,
            "review_matched_performers":   h_list_review,
        },
        pre_tool=pre_tool,
        after_tool=after_tool,
    )


# Earliest phase each tool belongs to — used to restrict tools on replay.
PHASE_TOOL_MIN = {
    "load_outreach_replies":           1,
    "ask_about_existing_research":     1,
    "load_existing_research":          1,
    "web_search":                      1,
    "notion_create_research_page":     1,
    "notion_list_performers_in_icpdb": 2,
    "notion_search_performer":         2,
    "request_performer_review":        2,
    "review_matched_performers":       2,
    "notion_create_performer":         2,
    "notion_list_shows":               2,
    "notion_search_show":              2,
    "generate_images":                 3,
    "notion_create_article_page":      4,
    "webflow_find_performers":         5,
    "webflow_create_blog_draft":       5,
}

_PHASE_LABELS = {1: "Research", 2: "Performer Matching", 3: "Image Generation",
                 4: "Writing Article", 5: "Publishing to Webflow"}


# ── Public entry points ───────────────────────────────────────────────────────

def run(month_label: str, verbose: bool = True) -> str:
    """CLI entry point — headless, conservative decisions."""
    run_id = mem.create_run(month_label)
    messages = [{"role": "user", "content": phase_prompt(month_label)}]
    if verbose:
        print(f"\n🤸 Starting performance review agent for {month_label}\n{'─'*60}")
    ctx = AgentContext(on_event=lambda e: None)
    try:
        result = run_loop(_make_spec(run_id), messages, ctx, verbose=verbose)
        mem.complete_run(run_id)
        return result
    except Exception as exc:
        mem.fail_run(run_id, str(exc))
        raise


def run_with_callbacks(
    month_label: str,
    on_event,
    check_pause=None,
    decide=None,
    run_id: str | None = None,
    replay_from: int = 1,
    cached_run: dict | None = None,
) -> str:
    """Host entry point — streams events via on_event; decisions via decide(kind, payload)."""
    if run_id is None:
        run_id = mem.create_run(month_label)

    on_event({"type": "run_id", "run_id": run_id})

    if replay_from > 1 and cached_run:
        user_msg = replay_prompt(month_label, cached_run, replay_from)
    else:
        user_msg = phase_prompt(month_label)

    messages = [{"role": "user", "content": user_msg}]

    # When replaying, restrict available tools to phases >= replay_from
    # so the model can't accidentally re-run earlier phases.
    active_tools = [t for t in TOOLS if PHASE_TOOL_MIN.get(t["name"], 1) >= replay_from]

    start_phase = max(1, replay_from)
    on_event({"type": "phase", "phase": start_phase,
              "label": _PHASE_LABELS.get(start_phase, "Working")})

    ctx = AgentContext(on_event=on_event, check_pause=check_pause, decide=decide)

    try:
        result = run_loop(_make_spec(run_id), messages, ctx, tools_override=active_tools)
        mem.complete_run(run_id)
        on_event({"type": "history_updated"})
        return result
    except Exception as exc:
        mem.fail_run(run_id, str(exc))
        raise
