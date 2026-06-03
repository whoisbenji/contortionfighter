"""
WebSocket server for the performance review agent dashboard.

Run with:
    uvicorn agent.server:app --reload --port 8765

Then open http://localhost:8765 in a browser.
"""

from __future__ import annotations

import os
from pathlib import Path

# Load .env from repo root before anything else
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

import asyncio
import json
import queue
import threading
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from . import config as cfg
from .agent import run_with_callbacks

app = FastAPI(title="Contortion Space Agent Dashboard")


# ── Connection manager ────────────────────────────────────────────────────────

class AgentSession:
    """
    Manages a single agent run connected to one WebSocket client.
    Queues:
      outbox:        agent → frontend  (events)
      inbox:         frontend → agent  (interject / resume messages)
      review_inbox:  frontend → agent  (performer review decisions)
    """

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.outbox: queue.Queue[dict | None]  = queue.Queue()
        self.inbox:  queue.Queue[str]          = queue.Queue()
        self.review_inbox: queue.Queue[dict]   = queue.Queue()
        self.pause_requested = threading.Event()
        self.thread: threading.Thread | None   = None

    # ── Callbacks passed into the agent ──────────────────────────────────

    def on_event(self, event: dict) -> None:
        self.outbox.put(event)

    def check_pause(self) -> str | None:
        if not self.pause_requested.is_set():
            try:
                msg = self.inbox.get_nowait()
                self.outbox.put({"type": "injected", "message": msg})
                return msg
            except queue.Empty:
                return None

        self.outbox.put({"type": "paused", "message": "Agent paused — waiting for your input."})
        self.pause_requested.clear()
        msg = self.inbox.get()
        self.outbox.put({"type": "resumed", "message": msg})
        return msg

    def get_performer_review(self, performers: list[dict]) -> dict:
        """Blocks the agent thread until the user submits performer decisions."""
        # The performer_review event was already emitted by the agent loop.
        # Wait for the user's response from the frontend.
        decisions = self.review_inbox.get()  # blocks
        return decisions

    # ── Start agent in background thread ─────────────────────────────────

    def start(self, month_label: str) -> None:
        def _run():
            try:
                run_with_callbacks(
                    month_label=month_label,
                    on_event=self.on_event,
                    check_pause=self.check_pause,
                    get_performer_review=self.get_performer_review,
                )
            except Exception as exc:
                self.outbox.put({"type": "error", "message": str(exc)})
            finally:
                self.outbox.put(None)

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session: AgentSession | None = None
    loop = asyncio.get_event_loop()

    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start', month:'...'}"}))
            return

        month_label = msg.get("month", "").strip()
        if not month_label:
            await ws.send_text(json.dumps({"type": "error", "message": "month is required"}))
            return

        # Apply admin-panel config overrides for this session
        db_config = msg.get("db_config", {})
        cfg.set_overrides(db_config)

        session = AgentSession(ws)
        session.start(month_label)

        await ws.send_text(json.dumps({"type": "started", "month": month_label}))

        async def _pump_outbox():
            while True:
                event = await loop.run_in_executor(None, session.outbox.get)
                if event is None:
                    await ws.send_text(json.dumps({"type": "done"}))
                    break
                await ws.send_text(json.dumps(event))

        async def _receive_controls():
            while True:
                try:
                    raw = await ws.receive_text()
                    ctrl = json.loads(raw)
                    ctrl_type = ctrl.get("type")
                    if ctrl_type == "interject":
                        session.inbox.put(ctrl.get("message", ""))
                    elif ctrl_type == "pause":
                        session.pause_requested.set()
                    elif ctrl_type == "resume":
                        try:
                            session.inbox.put_nowait(ctrl.get("message", ""))
                        except queue.Full:
                            pass
                    elif ctrl_type == "performer_decisions":
                        # decisions: [{name, action: "add"|"skip", instagram: "..."}]
                        session.review_inbox.put({"decisions": ctrl.get("decisions", [])})
                except WebSocketDisconnect:
                    break

        await asyncio.gather(_pump_outbox(), _receive_controls())

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass


# ── Serve dashboard HTML ──────────────────────────────────────────────────────

@app.get("/")
async def get_dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text())
