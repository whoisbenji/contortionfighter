"""
WebSocket server for the performance review agent dashboard.

Run with:
    uvicorn agent.server:app --reload --port 8765

Then open agent/dashboard.html in a browser.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .agent import run_with_callbacks

app = FastAPI(title="Contortion Space Agent Dashboard")


# ── Connection manager ────────────────────────────────────────────────────────

class AgentSession:
    """
    Manages a single agent run connected to one WebSocket client.
    Uses three thread-safe queues:
      - outbox:   agent  → frontend  (events)
      - inbox:    frontend → agent   (interject messages)
      - pause_flag: set to True to request a pause between tool calls
    """

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.outbox: queue.Queue[dict | None] = queue.Queue()
        self.inbox:  queue.Queue[str]         = queue.Queue()
        self.pause_requested = threading.Event()
        self.thread: threading.Thread | None = None

    # ── Callbacks passed into the agent ──────────────────────────────────

    def on_event(self, event: dict) -> None:
        """Called from agent thread — enqueue for async send."""
        self.outbox.put(event)

    def check_pause(self) -> str | None:
        """
        Called from agent thread between each tool call.
        Returns an interject message if one was submitted, else None.
        Blocks until user sends a resume if pause was requested.
        """
        if not self.pause_requested.is_set():
            # Check for queued interject without blocking
            try:
                msg = self.inbox.get_nowait()
                self.outbox.put({"type": "injected", "message": msg})
                return msg
            except queue.Empty:
                return None

        # Pause was requested — notify frontend and wait
        self.outbox.put({"type": "paused", "message": "Agent paused — waiting for your input."})
        self.pause_requested.clear()

        # Block until user sends something
        msg = self.inbox.get()   # blocks agent thread
        self.outbox.put({"type": "resumed", "message": msg})
        return msg

    # ── Start agent in background thread ─────────────────────────────────

    def start(self, month_label: str) -> None:
        def _run():
            try:
                run_with_callbacks(
                    month_label=month_label,
                    on_event=self.on_event,
                    check_pause=self.check_pause,
                )
            except Exception as exc:
                self.outbox.put({"type": "error", "message": str(exc)})
            finally:
                self.outbox.put(None)  # sentinel: stream finished

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session: AgentSession | None = None
    loop = asyncio.get_event_loop()

    try:
        # First message must be a "start" command
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start', month:'...'}"}))
            return

        month_label = msg.get("month", "").strip()
        if not month_label:
            await ws.send_text(json.dumps({"type": "error", "message": "month is required"}))
            return

        session = AgentSession(ws)
        session.start(month_label)

        await ws.send_text(json.dumps({"type": "started", "month": month_label}))

        # Pump outbox → WebSocket and receive control messages concurrently
        async def _pump_outbox():
            while True:
                # Poll outbox without blocking the event loop
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
                        # Put an empty resume to unblock if waiting
                        try:
                            session.inbox.put_nowait(ctrl.get("message", ""))
                        except queue.Full:
                            pass
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
