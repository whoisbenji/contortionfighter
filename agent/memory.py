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


def image_url(abs_path: str | None) -> str | None:
    """Convert an absolute output path to a /output/... URL for the dashboard."""
    if not abs_path:
        return None
    p = Path(abs_path)
    output_root = Path(__file__).parent.parent / "output"
    try:
        rel = p.relative_to(output_root)
        return f"/output/{rel.as_posix()}"
    except ValueError:
        return None
