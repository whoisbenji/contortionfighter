"""
Unified run store for all agents.

One SQLite table holds every agent run (Luzia reviews, Kooza maintenance,
Varekai outreach), keyed by agent name. Each run's full record is a JSON
document; the columns mirror the fields every query needs (agent, status,
timestamps) so listing stays cheap.

Why SQLite instead of the previous per-agent JSON files:
  • writes are atomic — the agent thread and server endpoints previously did
    racy read-modify-write cycles on shared JSON files
  • one file (agent_data.db) to back up instead of three
  • a new agent gets persistence for free: just pick an agent name

Legacy JSON histories (run_history.json, icpdb_history.json,
outreach_history.json) are imported automatically on first open and renamed
to *.migrated so they are never imported twice.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_FILE = Path(__file__).parent / "agent_data.db"

_LEGACY_FILES = {
    "luzia":   Path(__file__).parent / "run_history.json",
    "kooza":   Path(__file__).parent / "icpdb_history.json",
    "varekai": Path(__file__).parent / "outreach_history.json",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    agent        TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    completed_at TEXT,
    data         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs (agent, created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.executescript(_SCHEMA)
    _migrate_legacy(conn)
    return conn


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    for agent, path in _LEGACY_FILES.items():
        if not path.exists():
            continue
        try:
            runs = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
        except Exception:
            runs = []
        for run in runs:
            conn.execute(
                "INSERT OR IGNORE INTO runs (id, agent, status, created_at, completed_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run.get("id", f"{agent}-{int(time.time())}"), agent,
                 run.get("status", "completed"),
                 run.get("created_at", ""), run.get("completed_at"),
                 json.dumps(run, ensure_ascii=False)),
            )
        conn.commit()
        path.rename(path.with_suffix(path.suffix + ".migrated"))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── Public API ────────────────────────────────────────────────────────────────

def create_run(agent: str, run_id: str, record: dict) -> str:
    """Insert a new run. The record dict is stored verbatim (plus bookkeeping).

    Timestamp-based ids can collide when two runs start within the same
    second — on collision a numeric suffix is appended. Returns the final id.
    """
    record = {
        "id":               run_id,
        "created_at":       _now(),
        "completed_at":     None,
        "status":           "running",
        "phases_completed": [],
        "error":            None,
        **record,
    }
    with _connect() as conn:
        for attempt in range(100):
            candidate = run_id if attempt == 0 else f"{run_id}-{attempt + 1}"
            record["id"] = candidate
            try:
                conn.execute(
                    "INSERT INTO runs (id, agent, status, created_at, completed_at, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (candidate, agent, record["status"], record["created_at"],
                     record["completed_at"], json.dumps(record, ensure_ascii=False)),
                )
                return candidate
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError(f"Could not allocate a unique run id for {run_id}")


def get_run(run_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def update_run(run_id: str, updates: dict) -> None:
    """Merge updates into the run's record (single atomic transaction)."""
    with _connect() as conn:
        row = conn.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return
        record = json.loads(row[0])
        record.update(updates)
        conn.execute(
            "UPDATE runs SET status = ?, completed_at = ?, data = ? WHERE id = ?",
            (record.get("status", "running"), record.get("completed_at"),
             json.dumps(record, ensure_ascii=False), run_id),
        )


def save_phase(run_id: str, phase: int, phase_key: str | None, phase_data: dict) -> None:
    """Record a completed phase and its output under phase_key."""
    with _connect() as conn:
        row = conn.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return
        record = json.loads(row[0])
        if phase not in record.setdefault("phases_completed", []):
            record["phases_completed"].append(phase)
        if phase_key:
            record[phase_key] = phase_data
        conn.execute("UPDATE runs SET data = ? WHERE id = ?",
                     (json.dumps(record, ensure_ascii=False), run_id))


def complete_run(run_id: str) -> None:
    update_run(run_id, {"status": "completed", "completed_at": _now()})


def fail_run(run_id: str, error: str) -> None:
    update_run(run_id, {"status": "failed", "error": error})


def list_runs(agent: str) -> list[dict]:
    """All runs for an agent, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT data FROM runs WHERE agent = ? ORDER BY created_at DESC, rowid DESC",
            (agent,),
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def last_completed_run(agent: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT data FROM runs WHERE agent = ? AND status = 'completed' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (agent,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def run_counts() -> dict[str, int]:
    """Total runs per agent — used for platform status."""
    with _connect() as conn:
        rows = conn.execute("SELECT agent, COUNT(*) FROM runs GROUP BY agent").fetchall()
    return dict(rows)
