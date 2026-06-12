"""
The decision-kind registry.

Every human-in-the-loop decision an agent can request flows through
ctx.decide(kind, payload). This module defines, per kind:

  • chat_decision(kind, payload, say, ask) — render the request as a chat
    message and parse the user's free-text reply (used by Alegría).
  • default_decision(kind, payload)        — conservative headless answer.

The dashboard answers the same kinds via its own panels (see dashboard.html);
the event emitted to it is simply {"type": kind, **payload}.

Kinds and their decision shapes:
  research_question     -> str  (user's answer: "fresh" or a past month/run)
  performer_review      -> {"decisions": [{"name", "action": "add"|"skip"}]}
  performer_list_review -> str  (user's feedback, "ok" to approve)
  photo_check           -> {page_id: image_url, ...}
  update_proposals      -> {"decisions": [{"performer_id", "approved": bool}]}
  duplicate_proposals   -> {"decisions": [{"primary_id", "secondary_id", "approved": bool}]}
  outreach_queue (eligibility) -> {"confirmed_ids": [...]}
  outreach_queue (send_queue)  -> {"sent_ids": [...], "skipped_ids": [...]}
  outreach_reply_log    -> [{"page_id", "reply_text", "upcoming_shows", "status"}]
"""

from __future__ import annotations

import re
from typing import Any, Callable

Say = Callable[[str], None]   # send a chat message to the user
Ask = Callable[[], str]       # block until the user replies; returns their text


def _numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", text)}


def _is_all(text: str) -> bool:
    return not text or text in ("all", "yes", "ok", "approve all", "include all",
                                "include everyone", "everyone", "all of them", "merge all")


def _is_none(text: str) -> bool:
    return text in ("none", "no", "skip", "skip all", "reject all")


# ── Per-kind chat handlers ────────────────────────────────────────────────────

def _chat_research_question(payload: dict, say: Say, ask: Ask) -> str:
    past_runs = payload.get("past_runs", [])
    if not past_runs:
        say("**Luzia:** No past research found — starting fresh.")
        return "fresh"
    options = "\n".join(
        f"- **{r['month_label']}** ({r['created_at'][:10]})" for r in past_runs[:5]
    )
    say(
        "**Luzia:** Should I reuse existing research or run a fresh search?\n\n"
        f"Available past research:\n{options}\n\n"
        "Reply with a month label to reuse it, or **fresh** to research from scratch."
    )
    return ask() or "fresh"


def _chat_performer_review(payload: dict, say: Say, ask: Ask) -> dict:
    performers = payload.get("performers", [])
    if not performers:
        return {"decisions": []}
    lines = [
        f"**Found {len(performers)} unmatched performer(s).** "
        "Reply **all** to include everyone, or type the numbers to **skip** (e.g. `2, 4`):",
        "",
    ]
    for i, p in enumerate(performers, 1):
        detail = " — ".join(filter(None, [p.get("instagram") and f"@{p['instagram']}",
                                          p.get("context")]))
        lines.append(f"{i}. **{p.get('name', '?')}**{(' — ' + detail) if detail else ''}")
    say("\n".join(lines))
    resp = (ask() or "").strip().lower()
    if _is_all(resp):
        return {"decisions": [{"name": p["name"], "action": "add"} for p in performers]}
    skip = _numbers(resp)
    return {"decisions": [
        {"name": p["name"], "action": "skip" if i in skip else "add"}
        for i, p in enumerate(performers, 1)
    ]}


def _chat_performer_list_review(payload: dict, say: Say, ask: Ask) -> str:
    performers = payload.get("performers", [])
    lines = [
        f"**Matched performer list ({len(performers)}) — is anyone missing?**",
        "Reply **ok** to approve, or name performers/regions to double-check:",
        "",
    ]
    for p in performers:
        handle = f" (@{p['instagram']})" if p.get("instagram") else ""
        ctx = f" — {p['context']}" if p.get("context") else ""
        lines.append(f"- **{p.get('name', '?')}**{handle}{ctx}")
    say("\n".join(lines))
    return ask() or "ok"


def _chat_photo_check(payload: dict, say: Say, ask: Ask) -> dict:
    performers = payload.get("performers", [])
    missing = [p for p in performers if not p.get("has_photo")]
    if not missing:
        return {}
    lines = [
        f"**Photo check:** {len(performers)} performer(s) attached · "
        f"**{len(missing)} missing a Main photo.**",
        "Paste an image URL next to each name (`2: https://…`), or reply **skip**:",
        "",
    ]
    for i, p in enumerate(missing, 1):
        ig = f" (@{p['instagram']})" if p.get("instagram") else ""
        lines.append(f"{i}. **{p.get('name', '?')}**{ig}")
    say("\n".join(lines))

    resp = ask() or ""
    if resp.strip().lower() in ("skip", "none", ""):
        return {}
    urls: dict[str, str] = {}
    for line in resp.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)[.:]\s*(https?://\S+)", line)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(missing):
                urls[missing[idx]["page_id"]] = m.group(2)
        elif line.startswith("http"):
            for p in missing:
                if p["page_id"] not in urls:
                    urls[p["page_id"]] = line
                    break
    return urls


def _chat_update_proposals(payload: dict, say: Say, ask: Ask) -> dict:
    proposals = payload.get("proposals", [])
    if not proposals:
        return {"decisions": []}
    lines = [
        f"**Kooza proposes {len(proposals)} update(s).** "
        "Reply **all** to approve all, type numbers to approve specific ones, or **none**:",
        "",
    ]
    for i, p in enumerate(proposals, 1):
        lines.append(
            f"{i}. **{p.get('performer_name', p.get('performer_id', '?'))}** — "
            f"{p.get('field', '?')}: `{p.get('proposed_value', '?')}`"
        )
    say("\n".join(lines))
    resp = (ask() or "").strip().lower()
    if _is_none(resp):
        approved = set()
    elif _is_all(resp):
        approved = set(range(1, len(proposals) + 1))
    else:
        approved = _numbers(resp)
    return {"decisions": [
        {"performer_id": p["performer_id"], "approved": (i in approved)}
        for i, p in enumerate(proposals, 1)
    ]}


def _chat_duplicate_proposals(payload: dict, say: Say, ask: Ask) -> dict:
    groups = payload.get("groups", [])
    if not groups:
        return {"decisions": []}
    lines = [
        f"**Kooza found {len(groups)} possible duplicate(s).** "
        "Reply **all** to merge all, type numbers to approve specific merges, or **none**:",
        "",
    ]
    for i, g in enumerate(groups, 1):
        lines.append(
            f"{i}. **{g.get('primary_name', g.get('primary_id', '?'))}** ← keep "
            f"(merge with **{g.get('secondary_name', g.get('secondary_id', '?'))}**)"
        )
    say("\n".join(lines))
    resp = (ask() or "").strip().lower()
    if _is_none(resp):
        approved = set()
    elif _is_all(resp):
        approved = set(range(1, len(groups) + 1))
    else:
        approved = _numbers(resp)
    return {"decisions": [
        {"primary_id": g.get("primary_id"), "secondary_id": g.get("secondary_id"),
         "approved": (i in approved)}
        for i, g in enumerate(groups, 1)
    ]}


def _chat_outreach_queue(payload: dict, say: Say, ask: Ask) -> dict:
    performers = payload.get("performers", [])
    stage = payload.get("stage", "eligibility")

    if stage == "send_queue":
        lines = [
            f"**Varekai — {len(performers)} DM(s) ready to send.** "
            "Open each profile, send the message, then reply with the numbers you **sent** "
            "(e.g. `1, 3`), or **all** / **none**:",
            "",
        ]
        for i, d in enumerate(performers, 1):
            handle = d.get("instagram", "")
            link = f" — https://instagram.com/{handle}" if handle else ""
            msg = (d.get("message") or d.get("dm_text") or "")[:140]
            lines.append(f"{i}. **{d.get('name', '?')}**{link}\n   _{msg}_")
        say("\n".join(lines))
        resp = (ask() or "").strip().lower()
        if _is_none(resp):
            sent = set()
        elif _is_all(resp):
            sent = set(range(1, len(performers) + 1))
        else:
            sent = _numbers(resp)
        ids = [p.get("id") or p.get("page_id") for p in performers]
        return {
            "sent_ids":    [pid for i, pid in enumerate(ids, 1) if pid and i in sent],
            "skipped_ids": [pid for i, pid in enumerate(ids, 1) if pid and i not in sent],
        }

    # eligibility stage
    lines = [
        f"**Varekai — {len(performers)} performer(s) eligible for outreach.** "
        "Reply **all** to include everyone, or type numbers to **exclude** (e.g. `2, 5`):",
        "",
    ]
    for i, p in enumerate(performers, 1):
        handle = f" (@{p.get('instagram')})" if p.get("instagram") else ""
        lines.append(f"{i}. **{p.get('name', '?')}**{handle}")
    skipped = payload.get("skipped", [])
    if skipped:
        lines += ["", f"_{len(skipped)} excluded (recent contact / unsubscribed / no handle)._"]
    say("\n".join(lines))
    resp = (ask() or "").strip().lower()
    exclude = set() if _is_all(resp) else _numbers(resp)
    return {"confirmed_ids": [
        p.get("id") for i, p in enumerate(performers, 1)
        if p.get("id") and i not in exclude
    ]}


def _chat_outreach_reply_log(payload: dict, say: Say, ask: Ask) -> list:
    performers = payload.get("performers", [])
    if not performers:
        return []
    lines = [
        f"**Varekai — log replies for {len(performers)} performer(s).** "
        "Reply `N: <their reply>` per line; unlisted performers are logged as No Response:",
        "",
    ]
    for i, p in enumerate(performers, 1):
        handle = f" (@{p.get('instagram')})" if p.get("instagram") else ""
        lines.append(f"{i}. **{p.get('name', '?')}**{handle}")
    say("\n".join(lines))

    resp = ask() or ""
    decisions = []
    for i, p in enumerate(performers, 1):
        m = re.search(rf"^{i}[.:\)]\s*(.+)$", resp, re.MULTILINE)
        reply_text = m.group(1).strip() if m else ""
        decisions.append({
            "page_id":        p.get("id") or p.get("page_id", ""),
            "reply_text":     reply_text,
            "upcoming_shows": reply_text,
            "status":         "Replied" if reply_text else "No Response",
        })
    return decisions


CHAT_HANDLERS: dict[str, Callable[[dict, Say, Ask], Any]] = {
    "research_question":     _chat_research_question,
    "performer_review":      _chat_performer_review,
    "performer_list_review": _chat_performer_list_review,
    "photo_check":           _chat_photo_check,
    "update_proposals":      _chat_update_proposals,
    "duplicate_proposals":   _chat_duplicate_proposals,
    "outreach_queue":        _chat_outreach_queue,
    "outreach_reply_log":    _chat_outreach_reply_log,
}


def chat_decision(kind: str, payload: dict, say: Say, ask: Ask) -> Any:
    """Render a decision request in chat and parse the user's reply."""
    handler = CHAT_HANDLERS.get(kind)
    if handler is None:
        # Unknown kind — surface it and pass the raw reply through.
        say(f"**Decision needed ({kind}):**\n```\n{str(payload)[:800]}\n```")
        return ask() or ""
    return handler(payload, say, ask)


# ── Headless defaults ─────────────────────────────────────────────────────────

def default_decision(kind: str, payload: dict) -> Any:
    """Conservative answers for unattended runs: decline/skip everything."""
    if kind == "research_question":
        return "fresh"
    if kind == "performer_review":
        return {"decisions": [{"name": p["name"], "action": "skip"}
                              for p in payload.get("performers", [])]}
    if kind == "performer_list_review":
        return "ok"
    if kind == "photo_check":
        return {}
    if kind == "update_proposals":
        return {"decisions": [{"performer_id": p["performer_id"], "approved": False}
                              for p in payload.get("proposals", [])]}
    if kind == "duplicate_proposals":
        return {"decisions": [{"primary_id": g.get("primary_id"),
                               "secondary_id": g.get("secondary_id"), "approved": False}
                              for g in payload.get("groups", [])]}
    if kind == "outreach_queue":
        if payload.get("stage") == "send_queue":
            return {"sent_ids": [], "skipped_ids": []}
        return {"confirmed_ids": [p.get("id") for p in payload.get("performers", []) if p.get("id")]}
    if kind == "outreach_reply_log":
        return []
    return ""
