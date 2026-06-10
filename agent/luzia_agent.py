"""
Core agent loop. Uses the Anthropic SDK with tool_use to drive the
four-phase performance review workflow.
"""

from __future__ import annotations
import json
import os
import time
from typing import Any

import anthropic

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

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

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


def _stream_response(client, on_event, **kwargs):
    """Stream a response, emitting thinking_delta events for text tokens."""
    delays = [10, 30, 60, 120]
    for attempt, delay in enumerate(delays + [None]):
        try:
            thinking_id = f"thinking-{int(time.time()*1000)}"
            text_buf = []
            with client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and hasattr(event, "delta")
                        and getattr(event.delta, "type", "") == "text_delta"
                    ):
                        chunk = event.delta.text
                        if chunk:
                            text_buf.append(chunk)
                            on_event({"type": "thinking_delta", "id": thinking_id, "text": chunk})
            if text_buf:
                on_event({"type": "thinking_done", "id": thinking_id})
            return stream.get_final_message()
        except anthropic.RateLimitError:
            if delay is None:
                raise
            time.sleep(delay)
        except anthropic.APIStatusError as exc:
            if exc.status_code == 429 and delay is not None:
                time.sleep(delay)
            else:
                raise


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

_NOOP_EVENT      = lambda event: None
_NOOP_PAUSE      = lambda: None
_NOOP_REVIEW     = lambda performers: {"decisions": [{"name": p["name"], "action": "skip"} for p in performers]}
_NOOP_USER_INPUT = lambda: "no"
_NOOP_PHOTO_URLS = lambda performers: {}  # proceed without collecting missing photos


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


# ── Core loop ─────────────────────────────────────────────────────────────────

def _loop(
    month_label: str,
    messages: list[dict],
    on_event,
    check_pause,
    get_performer_review,
    get_user_input,
    get_photo_urls,
    run_id: str,
    verbose: bool,
    tools_override: list[dict] | None = None,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    active_tools = tools_override if tools_override is not None else TOOLS
    current_phase = 0
    # Accumulate matching data across tool calls for phase 2 save
    _matched_ids: list[str] = []
    _matched_names: list[str] = []
    _show_ids: list[str] = []

    while True:
        on_event({"type": "thinking"})

        response = _stream_response(
            client,
            on_event,
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
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

            # ── Ask about existing research: block for user input ─────────
            if tool_name == "ask_about_existing_research":
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
                on_event({"type": "research_question", "past_runs": past_runs})
                user_answer = get_user_input()
                result = {"answer": user_answer, "past_runs": past_runs}
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
                on_event({
                    "type":   "tool_result",
                    "tool":   tool_name,
                    "result": f"User answered: {user_answer[:200]}",
                    "ok":     True,
                })
                continue

            # ── Matched performer list review: block for user input ──────
            if tool_name == "review_matched_performers":
                performers = tool_input.get("matched_performers", [])
                on_event({"type": "performer_list_review", "performers": performers})
                user_response = get_user_input()
                result = {"user_response": user_response or "ok"}
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
                on_event({
                    "type":   "tool_result",
                    "tool":   tool_name,
                    "result": f"User responded: {(user_response or 'ok')[:200]}",
                    "ok":     True,
                })
                continue

            # ── Performer review: block until user responds ───────────────
            if tool_name == "request_performer_review":
                performers = tool_input.get("unmatched_performers", [])
                on_event({"type": "performer_review", "performers": performers})
                result = get_performer_review(performers)
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

            # ── Photo check before image generation ──────────────────────
            if tool_name == "generate_images":
                performer_ids = tool_input.get("performer_page_ids", [])
                performers = check_performer_photos(performer_ids)
                missing_count = sum(1 for p in performers if not p["has_photo"])
                on_event({
                    "type":          "photo_check",
                    "performers":    performers,
                    "missing_count": missing_count,
                })
                photo_urls = get_photo_urls(performers)
                # Write provided URLs back to Notion
                for pid, url in (photo_urls or {}).items():
                    if url and url.strip():
                        try:
                            set_performer_photo(pid, url.strip())
                            on_event({"type": "tool_result", "tool": "set_performer_photo",
                                      "result": f"Photo saved for {pid}", "ok": True})
                        except Exception as exc:
                            on_event({"type": "tool_result", "tool": "set_performer_photo",
                                      "result": f"Failed to save photo: {exc}", "ok": False})

            # ── Pause / interject check ───────────────────────────────────
            interject = check_pause()
            if interject:
                messages.append({"role": "user", "content": (
                    f"[User interjection]: {interject}\n"
                    "Please take this into account and adjust your next action accordingly."
                )})
                on_event({"type": "thinking"})
                rethink = _stream_response(
                    client,
                    on_event,
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
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
            phase_out = _extract_phase_output(tool_name, tool_input, result)
            if phase_out and run_id:
                phase_num_out, phase_data = phase_out
                mem.save_phase(run_id, phase_num_out, phase_data)
                on_event({"type": "phase_saved", "phase": phase_num_out})

            # Accumulate performer/show IDs for phase 2 save
            if tool_name == "notion_create_performer" and "error" not in result:
                _matched_ids.append(result.get("page_id", ""))
                _matched_names.append(result.get("name", ""))
            if tool_name == "notion_create_article_page" and "error" not in result:
                # Save phase 2 matching data using what we accumulated + what the call had
                p_ids = tool_input.get("performer_page_ids", [])
                s_ids = tool_input.get("show_page_ids", [])
                if run_id:
                    mem.save_phase(run_id, 2, {
                        "performer_page_ids": p_ids,
                        "show_page_ids":      s_ids,
                        "performer_names":    _matched_names,
                    })

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
    """CLI entry point."""
    run_id = mem.create_run(month_label)
    messages = [{"role": "user", "content": phase_prompt(month_label)}]
    if verbose:
        print(f"\n🤸 Starting performance review agent for {month_label}\n{'─'*60}")
    try:
        result = _loop(month_label, messages, _NOOP_EVENT, _NOOP_PAUSE, _NOOP_REVIEW, _NOOP_USER_INPUT, _NOOP_PHOTO_URLS, run_id, verbose)
        mem.complete_run(run_id)
        return result
    except Exception as exc:
        mem.fail_run(run_id, str(exc))
        raise


def run_with_callbacks(
    month_label: str,
    on_event,
    check_pause,
    get_performer_review,
    get_user_input=None,
    get_photo_urls=None,
    run_id: str | None = None,
    replay_from: int = 1,
    cached_run: dict | None = None,
) -> str:
    """Dashboard entry point — streams events via callbacks."""
    if run_id is None:
        run_id = mem.create_run(month_label)

    on_event({"type": "run_id", "run_id": run_id})

    if replay_from > 1 and cached_run:
        user_msg = replay_prompt(month_label, cached_run, replay_from)
    else:
        user_msg = phase_prompt(month_label)

    messages = [{"role": "user", "content": user_msg}]

    # When replaying, restrict available tools to only phases >= replay_from
    # so the model can't accidentally re-run earlier phases
    phase_tool_min = {
        "load_outreach_replies":        1,
        "ask_about_existing_research": 1,
        "load_existing_research":      1,
        "web_search": 1,
        "notion_create_research_page": 1,
        "notion_list_performers_in_icpdb": 2,
        "notion_search_performer": 2,
        "request_performer_review": 2,
        "review_matched_performers": 2,
        "notion_create_performer": 2,
        "notion_list_shows": 2,
        "notion_search_show": 2,
        "generate_images": 3,
        "notion_create_article_page": 4,
        "webflow_find_performers": 5,
        "webflow_create_blog_draft": 5,
    }
    active_tools = [t for t in TOOLS if phase_tool_min.get(t["name"], 1) >= replay_from]

    start_phase = max(1, replay_from)
    on_event({"type": "phase", "phase": start_phase,
              "label": {1:"Research",2:"Performer Matching",3:"Image Generation",
                        4:"Writing Article",5:"Publishing to Webflow"}.get(start_phase,"Working")})

    _get_user_input  = get_user_input  if get_user_input  is not None else _NOOP_USER_INPUT
    _get_photo_urls  = get_photo_urls  if get_photo_urls  is not None else _NOOP_PHOTO_URLS

    # ask_about_existing_research is only meaningful for a fresh run (not replay)
    active_tools_with_ask = active_tools
    if replay_from <= 1:
        ask_tools = [t for t in TOOLS if t["name"] in ("ask_about_existing_research", "load_existing_research")]
        existing_names = {t["name"] for t in active_tools}
        active_tools_with_ask = ask_tools + [t for t in active_tools if t["name"] not in {at["name"] for at in ask_tools}]
    else:
        active_tools_with_ask = active_tools

    try:
        result = _loop(month_label, messages, on_event, check_pause, get_performer_review,
                       _get_user_input, _get_photo_urls, run_id, verbose=False, tools_override=active_tools_with_ask)
        mem.complete_run(run_id)
        on_event({"type": "history_updated"})
        return result
    except Exception as exc:
        mem.fail_run(run_id, str(exc))
        raise
