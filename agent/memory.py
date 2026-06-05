"""
Run history and memory for the performance review agent.
Stores phase outputs locally so runs can be replayed from any phase.
"""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

HISTORY_FILE = Path(__file__).parent / "run_history.json"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"runs": []}


def _save(data: dict) -> None:
    HISTORY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Public API ────────────────────────────────────────────────────────────────

def create_run(month_label: str) -> str:
    """Create a new run record and return its ID."""
    data = _load()
    run_id = f"{month_label.lower().replace(' ', '-')}-{int(time.time())}"
    run: dict[str, Any] = {
        "id":               run_id,
        "month_label":      month_label,
        "created_at":       time.strftime("%Y-%m-%dT%H:%M:%S"),
        "completed_at":     None,
        "status":           "running",
        "phases_completed": [],
        "research":         None,   # {notion_page_id, notion_url, content_markdown}
        "matching":         None,   # {performer_page_ids, show_page_ids, performer_names}
        "images":           None,   # {story_path, header_path, webflow_asset_id}
        "article":          None,   # {notion_page_id, notion_url, body_markdown}
        "webflow":          None,   # {item_id, draft_url, editor_url}
        "feedback":         "",
        "error":            None,
    }
    data["runs"].insert(0, run)
    _save(data)
    return run_id


def _update(run_id: str, **kwargs) -> None:
    data = _load()
    for run in data["runs"]:
        if run["id"] == run_id:
            run.update(kwargs)
            break
    _save(data)


PHASE_KEYS = {1: "research", 2: "matching", 3: "images", 4: "article", 5: "webflow"}


def save_phase(run_id: str, phase: int, phase_data: dict) -> None:
    """Persist output from a completed phase."""
    data = _load()
    for run in data["runs"]:
        if run["id"] == run_id:
            if phase not in run["phases_completed"]:
                run["phases_completed"].append(phase)
            key = PHASE_KEYS.get(phase)
            if key:
                run[key] = phase_data
            break
    _save(data)


def complete_run(run_id: str) -> None:
    _update(run_id, status="completed",
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def fail_run(run_id: str, error: str) -> None:
    _update(run_id, status="failed", error=error)


def add_feedback(run_id: str, feedback: str) -> None:
    _update(run_id, feedback=feedback)


def load_all_runs() -> list[dict]:
    return _load().get("runs", [])


def get_run(run_id: str) -> dict | None:
    for run in _load().get("runs", []):
        if run["id"] == run_id:
            return run
    return None


# ── ICPDB history ─────────────────────────────────────────────────────────────

ICPDB_HISTORY_FILE = Path(__file__).parent / "icpdb_history.json"


def _icpdb_load() -> dict:
    if ICPDB_HISTORY_FILE.exists():
        try:
            return json.loads(ICPDB_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"runs": []}


def _icpdb_save(data: dict) -> None:
    ICPDB_HISTORY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_icpdb_run(run_mode: str) -> str:
    data = _icpdb_load()
    run_id = f"icpdb-{run_mode}-{int(time.time())}"
    run: dict[str, Any] = {
        "id":               run_id,
        "run_mode":         run_mode,
        "created_at":       time.strftime("%Y-%m-%dT%H:%M:%S"),
        "completed_at":     None,
        "status":           "running",
        "phases_completed": [],
        "audit":            None,
        "research":         None,
        "review":           None,
        "apply":            None,
        "outreach":         None,
        "error":            None,
    }
    data["runs"].insert(0, run)
    _icpdb_save(data)
    return run_id


def _icpdb_update(run_id: str, **kwargs) -> None:
    data = _icpdb_load()
    for run in data["runs"]:
        if run["id"] == run_id:
            run.update(kwargs)
            break
    _icpdb_save(data)


_ICPDB_PHASE_KEYS = {1: "audit", 2: "research", 3: "review", 4: "apply", 5: "outreach"}


def save_icpdb_phase(run_id: str, phase: int, data: dict) -> None:
    db = _icpdb_load()
    for run in db["runs"]:
        if run["id"] == run_id:
            if phase not in run["phases_completed"]:
                run["phases_completed"].append(phase)
            key = _ICPDB_PHASE_KEYS.get(phase)
            if key:
                run[key] = data
            break
    _icpdb_save(db)


def complete_icpdb_run(run_id: str) -> None:
    _icpdb_update(run_id, status="completed",
                  completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def fail_icpdb_run(run_id: str, error: str) -> None:
    _icpdb_update(run_id, status="failed", error=error)


def load_icpdb_runs() -> list[dict]:
    return _icpdb_load().get("runs", [])


def get_icpdb_run(run_id: str) -> dict | None:
    for run in _icpdb_load().get("runs", []):
        if run["id"] == run_id:
            return run
    return None


def get_last_icpdb_audit() -> dict | None:
    """Return audit data from the most recent completed ICPDB run that has it."""
    for run in _icpdb_load().get("runs", []):
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

