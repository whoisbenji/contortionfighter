"""
Run history and memory for the Contortion Space agents.

Run records live in the unified SQLite store (run_store.py), one table for
all agents. The per-agent functions below are thin wrappers that keep the
established call sites (agents, server, dashboard) unchanged.

Chat history, memories, and preferences remain small JSON files.
"""

from __future__ import annotations
import json
import time
from pathlib import Path

from . import run_store


# ── Luzia (performance review) runs ──────────────────────────────────────────

PHASE_KEYS = {1: "research", 2: "matching", 3: "images", 4: "article", 5: "webflow"}


def create_run(month_label: str) -> str:
    run_id = f"{month_label.lower().replace(' ', '-')}-{int(time.time())}"
    return run_store.create_run("luzia", run_id, {
        "month_label": month_label,
        "research":    None,   # {notion_page_id, notion_url, content_markdown}
        "matching":    None,   # {performer_page_ids, show_page_ids, performer_names}
        "images":      None,   # {story_path, header_path, webflow_asset_id}
        "article":     None,   # {notion_page_id, notion_url, body_markdown}
        "webflow":     None,   # {item_id, draft_url, editor_url}
        "feedback":    "",
    })


def save_phase(run_id: str, phase: int, phase_data: dict) -> None:
    run_store.save_phase(run_id, phase, PHASE_KEYS.get(phase), phase_data)


def complete_run(run_id: str) -> None:
    run_store.complete_run(run_id)


def fail_run(run_id: str, error: str) -> None:
    run_store.fail_run(run_id, error)


def add_feedback(run_id: str, feedback: str) -> None:
    run_store.update_run(run_id, {"feedback": feedback})


def load_all_runs() -> list[dict]:
    return run_store.list_runs("luzia")


def get_run(run_id: str) -> dict | None:
    return run_store.get_run(run_id)


# ── Kooza (ICPDB maintenance) runs ────────────────────────────────────────────

_ICPDB_PHASE_KEYS = {1: "audit", 2: "research", 3: "review", 4: "apply", 5: "outreach"}


def create_icpdb_run(run_mode: str) -> str:
    run_id = f"icpdb-{run_mode}-{int(time.time())}"
    return run_store.create_run("kooza", run_id, {
        "run_mode": run_mode,
        "audit":    None,
        "research": None,
        "review":   None,
        "apply":    None,
        "outreach": None,
    })


def save_icpdb_phase(run_id: str, phase: int, data: dict) -> None:
    run_store.save_phase(run_id, phase, _ICPDB_PHASE_KEYS.get(phase), data)


def complete_icpdb_run(run_id: str) -> None:
    run_store.complete_run(run_id)


def fail_icpdb_run(run_id: str, error: str) -> None:
    run_store.fail_run(run_id, error)


def load_icpdb_runs() -> list[dict]:
    return run_store.list_runs("kooza")


def get_icpdb_run(run_id: str) -> dict | None:
    return run_store.get_run(run_id)


def get_last_icpdb_audit() -> dict | None:
    """Return audit data from the most recent completed ICPDB run that has it."""
    for run in run_store.list_runs("kooza"):
        if run.get("status") == "completed" and run.get("audit"):
            return run["audit"]
    return None


# ── ICPDB user preferences ───────────────────────────────────────────────────

ICPDB_PREFS_FILE = Path(__file__).parent / "icpdb_prefs.json"

_DEFAULT_PREFS: dict = {
    "priority_fields": [],   # list of field names in priority order
    "notes": "",             # free-text guidance for the agent
}


def get_icpdb_prefs() -> dict:
    """Return the stored ICPDB preferences, falling back to defaults."""
    if ICPDB_PREFS_FILE.exists():
        try:
            stored = json.loads(ICPDB_PREFS_FILE.read_text(encoding="utf-8"))
            return {**_DEFAULT_PREFS, **stored}
        except Exception:
            pass
    return dict(_DEFAULT_PREFS)


def save_icpdb_prefs(prefs: dict) -> None:
    """Persist ICPDB preferences."""
    current = get_icpdb_prefs()
    current.update({k: v for k, v in prefs.items() if k in _DEFAULT_PREFS})
    ICPDB_PREFS_FILE.write_text(
        json.dumps(current, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def image_url(abs_path: str | None) -> str | None:
    """Convert an output path to a /output/... URL for the dashboard."""
    if not abs_path:
        return None
    output_root = (Path(__file__).parent.parent / "output").resolve()
    try:
        rel = Path(abs_path).resolve().relative_to(output_root)
        return f"/output/{rel.as_posix()}"
    except ValueError:
        return None


# ── Alegría conversation memory ───────────────────────────────────────────────

ALEGRIA_HISTORY_FILE = Path(__file__).parent / "alegria_history.json"
ALEGRIA_MEMORIES_FILE = Path(__file__).parent / "alegria_memories.json"

_MAX_HISTORY = 80   # messages to persist
_LOAD_LIMIT  = 60   # messages to load into context


def save_alegria_messages(messages: list[dict]) -> None:
    """Persist the last _MAX_HISTORY text-only user/assistant messages."""
    text_only = [m for m in messages if isinstance(m.get("content"), str)]
    kept = text_only[-_MAX_HISTORY:]
    ALEGRIA_HISTORY_FILE.write_text(
        json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_alegria_messages() -> list[dict]:
    """Return up to _LOAD_LIMIT persisted messages."""
    if not ALEGRIA_HISTORY_FILE.exists():
        return []
    try:
        msgs = json.loads(ALEGRIA_HISTORY_FILE.read_text(encoding="utf-8"))
        return msgs[-_LOAD_LIMIT:]
    except Exception:
        return []


def clear_alegria_history() -> None:
    ALEGRIA_HISTORY_FILE.write_text("[]", encoding="utf-8")


def save_alegria_memory(text: str) -> None:
    """Append a memory note (key fact or preference) for future sessions."""
    memories: list[dict] = []
    if ALEGRIA_MEMORIES_FILE.exists():
        try:
            memories = json.loads(ALEGRIA_MEMORIES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    memories.append({"text": text, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    ALEGRIA_MEMORIES_FILE.write_text(
        json.dumps(memories[-50:], indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_alegria_memories() -> list[str]:
    """Return all saved memory notes as plain strings."""
    if not ALEGRIA_MEMORIES_FILE.exists():
        return []
    try:
        return [m["text"] for m in json.loads(ALEGRIA_MEMORIES_FILE.read_text(encoding="utf-8"))
                if isinstance(m, dict) and m.get("text")]
    except Exception:
        return []


def get_alegria_history_for_display() -> list[dict]:
    """Return history with role+content for the dashboard to render."""
    return load_alegria_messages()


# ── Varekai outreach runs ─────────────────────────────────────────────────────

_OUTREACH_PHASE_KEYS = {1: "phase1", 2: "phase2", 3: "phase3"}


def create_outreach_run(run_mode: str = "full") -> str:
    run_id = f"outreach-{run_mode}-{int(time.time())}"
    return run_store.create_run("varekai", run_id, {
        "run_mode": run_mode,
        "phase1":   None,   # {eligible_count, confirmed_count}
        "phase2":   None,   # {sent_count, skipped_count, performer_ids_contacted}
        "phase3":   None,   # {replies_logged}
    })


def save_outreach_phase(run_id: str, phase: int, phase_data: dict) -> None:
    run_store.save_phase(run_id, phase, _OUTREACH_PHASE_KEYS.get(phase), phase_data)


def complete_outreach_run(run_id: str) -> None:
    run_store.complete_run(run_id)


def fail_outreach_run(run_id: str, error: str) -> None:
    run_store.fail_run(run_id, error)


def load_outreach_runs() -> list[dict]:
    return run_store.list_runs("varekai")


def get_last_outreach_run() -> dict | None:
    return run_store.last_completed_run("varekai")

