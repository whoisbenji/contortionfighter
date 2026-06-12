"""
The due-tasks engine — the platform's operating rhythm.

One place computes what the organisation should do next:
  • Luzia   — the monthly roundup for the current month
  • Varekai — the quarterly (90-day) outreach cycle
  • Kooza   — ICPDB upkeep: stale audit or low health score

get_tasks() returns every recurring task with its current state; it powers
Alegría's system prompt (so she nudges proactively), the /api/tasks endpoint,
and the dashboard overview banner. Adding a new recurring duty means adding
one entry here — every surface picks it up automatically.
"""

from __future__ import annotations

from datetime import date, datetime

from . import run_store

OUTREACH_CYCLE_DAYS = 90
AUDIT_STALE_DAYS = 30
HEALTH_THRESHOLD = 75


def _days_since(iso_timestamp: str | None) -> int | None:
    if not iso_timestamp:
        return None
    try:
        return (date.today() - date.fromisoformat(iso_timestamp[:10])).days
    except ValueError:
        return None


def _luzia_task(today: date) -> dict:
    month_label = today.strftime("%B %Y")
    done = any(
        r.get("month_label") == month_label and r.get("status") == "completed"
        for r in run_store.list_runs("luzia")
    )
    return {
        "id":     "monthly_roundup",
        "agent":  "luzia",
        "label":  f"Monthly roundup — {month_label}",
        "due":    not done,
        "detail": (f"The {month_label} roundup has not been published yet."
                   if not done else f"The {month_label} roundup is done."),
        "action": {"tool": "run_luzia", "params": {"month_label": month_label}},
    }


def _varekai_task() -> dict:
    last = run_store.last_completed_run("varekai")
    days = _days_since((last or {}).get("completed_at") or (last or {}).get("created_at"))
    if days is None:
        due, detail, next_due_in = True, "Performer outreach has never been run.", 0
    else:
        due = days >= OUTREACH_CYCLE_DAYS
        next_due_in = max(0, OUTREACH_CYCLE_DAYS - days)
        detail = (f"Last outreach was {days} days ago — the quarterly cycle is due."
                  if due else f"Last outreach was {days} days ago; next due in {next_due_in} days.")
    return {
        "id":     "quarterly_outreach",
        "agent":  "varekai",
        "label":  "Quarterly performer outreach",
        "due":    due,
        "detail": detail,
        "days_since_last": days,
        "next_due_in":     next_due_in,
        "last_run_date":   ((last or {}).get("completed_at") or "")[:10] or None,
        "action": {"tool": "run_varekai", "params": {"run_mode": "full"}},
    }


def _kooza_task() -> dict:
    last_audit_run = next(
        (r for r in run_store.list_runs("kooza")
         if r.get("status") == "completed" and r.get("audit")),
        None,
    )
    if last_audit_run is None:
        return {
            "id": "icpdb_health", "agent": "kooza",
            "label": "ICPDB maintenance", "due": True,
            "detail": "The ICPDB has never been audited.",
            "action": {"tool": "run_kooza", "params": {"run_mode": "full"}},
        }

    days = _days_since(last_audit_run.get("completed_at") or last_audit_run.get("created_at"))
    health = last_audit_run["audit"].get("health_score", 0)

    if days is not None and days >= AUDIT_STALE_DAYS:
        due, detail = True, f"Last ICPDB audit was {days} days ago — time for a fresh maintenance pass."
    elif health < HEALTH_THRESHOLD:
        due, detail = True, f"ICPDB health score is {health}/100 (target {HEALTH_THRESHOLD}+) — run maintenance to fill gaps."
    else:
        due, detail = False, f"ICPDB health score {health}/100; audited {days} days ago."

    return {
        "id":     "icpdb_health",
        "agent":  "kooza",
        "label":  "ICPDB maintenance",
        "due":    due,
        "detail": detail,
        "health_score":    health,
        "days_since_last": days,
        "action": {"tool": "run_kooza", "params": {"run_mode": "full"}},
    }


def get_tasks() -> list[dict]:
    """All recurring tasks with their current due-state, due ones first."""
    today = date.today()
    tasks = [_luzia_task(today), _varekai_task(), _kooza_task()]
    return sorted(tasks, key=lambda t: not t["due"])


def get_due_tasks() -> list[dict]:
    return [t for t in get_tasks() if t["due"]]


def tasks_summary_lines() -> list[str]:
    """One line per task — used in Alegría's system prompt."""
    lines = []
    for t in get_tasks():
        marker = "⚠ DUE" if t["due"] else "✓ ok"
        lines.append(f"[{marker}] {t['label']}: {t['detail']}")
    return lines
