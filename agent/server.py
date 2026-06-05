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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles

from . import config as cfg
from . import memory as mem
from .luzia_agent import run_with_callbacks
from . import kooza_agent
from . import alegria_agent

app = FastAPI(title="Contortion Space Agent Dashboard")

# Serve generated images at /output/...
_output_dir = Path(__file__).parent.parent / "output"
_output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_output_dir)), name="output")


# ── AgentSession ─────────────────────────────────────────────────────────────

class AgentSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.outbox:       queue.Queue[dict | None] = queue.Queue()
        self.inbox:        queue.Queue[str]         = queue.Queue()
        self.review_inbox: queue.Queue[dict]        = queue.Queue()
        self.user_input_inbox: queue.Queue[str]     = queue.Queue()
        self.pause_requested = threading.Event()
        self.thread: threading.Thread | None = None

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
        return self.review_inbox.get()

    def get_user_input(self) -> str:
        return self.user_input_inbox.get()

    def start(self, month_label: str, run_id: str | None,
              replay_from: int, cached_run: dict | None) -> None:
        def _run():
            try:
                run_with_callbacks(
                    month_label=month_label,
                    on_event=self.on_event,
                    check_pause=self.check_pause,
                    get_performer_review=self.get_performer_review,
                    get_user_input=self.get_user_input,
                    run_id=run_id,
                    replay_from=replay_from,
                    cached_run=cached_run,
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

        # Apply admin-panel config overrides
        cfg.set_overrides(msg.get("db_config", {}))

        # Replay support
        replay_from   = int(msg.get("replay_from", 1))
        replay_run_id = msg.get("replay_run_id")
        cached_run    = mem.get_run(replay_run_id) if replay_run_id else None

        session = AgentSession(ws)
        session.start(month_label, replay_run_id, replay_from, cached_run)

        await ws.send_text(json.dumps({
            "type": "started", "month": month_label,
            "replay_from": replay_from,
        }))

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
                    t = ctrl.get("type")
                    if t == "interject":
                        session.inbox.put(ctrl.get("message", ""))
                    elif t == "pause":
                        session.pause_requested.set()
                    elif t == "resume":
                        try:
                            session.inbox.put_nowait(ctrl.get("message", ""))
                        except queue.Full:
                            pass
                    elif t == "performer_decisions":
                        session.review_inbox.put({"decisions": ctrl.get("decisions", [])})
                    elif t == "user_input":
                        session.user_input_inbox.put(ctrl.get("message", ""))
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


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history():
    runs = mem.load_all_runs()
    slim = []
    for r in runs:
        s = {k: v for k, v in r.items() if k not in ("research", "article")}
        if r.get("research"):
            s["research"] = {k: v for k, v in r["research"].items() if k != "content_markdown"}
        if r.get("article"):
            s["article"] = {k: v for k, v in r["article"].items() if k != "body_markdown"}
        if r.get("images"):
            s["story_url"]  = mem.image_url(r["images"].get("story_path"))
            s["header_url"] = mem.image_url(r["images"].get("header_path"))
        slim.append(s)
    return JSONResponse(slim)


@app.post("/api/feedback")
async def save_feedback(request: Request):
    body = await request.json()
    run_id   = body.get("run_id", "")
    feedback = body.get("feedback", "")
    if not run_id:
        return JSONResponse({"error": "run_id required"}, status_code=400)
    mem.add_feedback(run_id, feedback)
    return JSONResponse({"ok": True})


# ── Serve dashboard HTML ──────────────────────────────────────────────────────

# ── ICPDBSession ──────────────────────────────────────────────────────────────

class ICPDBSession:
    def __init__(self, ws: WebSocket, prefs: dict | None = None):
        self.ws = ws
        self.prefs = prefs or {}
        self.outbox:                 queue.Queue[dict | None] = queue.Queue()
        self.inbox:                  queue.Queue[str]         = queue.Queue()
        self.update_decisions_inbox: queue.Queue[dict]        = queue.Queue()
        self.pause_requested = threading.Event()
        self.thread: threading.Thread | None = None

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

    def get_update_decisions(self, proposals: list[dict]) -> dict:
        return self.update_decisions_inbox.get()

    def start(self, run_mode: str) -> None:
        def _run():
            try:
                kooza_agent.run_with_callbacks(
                    on_event=self.on_event,
                    check_pause=self.check_pause,
                    get_update_decisions=self.get_update_decisions,
                    run_mode=run_mode,
                    prefs=self.prefs,
                )
            except Exception as exc:
                self.outbox.put({"type": "error", "message": str(exc)})
            finally:
                self.outbox.put(None)

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()


# ── ICPDB WebSocket endpoint ──────────────────────────────────────────────────

@app.websocket("/ws/icpdb")
async def icpdb_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session: ICPDBSession | None = None
    loop = asyncio.get_event_loop()

    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start', run_mode:'...'}"}))
            return

        run_mode = msg.get("run_mode", "full")
        prefs = mem.get_icpdb_prefs()
        session = ICPDBSession(ws, prefs=prefs)
        session.start(run_mode)

        await ws.send_text(json.dumps({"type": "started", "run_mode": run_mode}))

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
                    t = ctrl.get("type")
                    if t == "interject":
                        session.inbox.put(ctrl.get("message", ""))
                    elif t == "pause":
                        session.pause_requested.set()
                    elif t == "resume":
                        try:
                            session.inbox.put_nowait(ctrl.get("message", ""))
                        except queue.Full:
                            pass
                    elif t == "update_decisions":
                        session.update_decisions_inbox.put({"decisions": ctrl.get("decisions", [])})
                    elif t == "dedup_decisions":
                        session.update_decisions_inbox.put({"decisions": ctrl.get("decisions", [])})
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


# ── ICPDB stats endpoint ──────────────────────────────────────────────────────

@app.get("/api/icpdb/prefs")
async def get_icpdb_prefs():
    return JSONResponse(mem.get_icpdb_prefs())


@app.post("/api/icpdb/prefs")
async def save_icpdb_prefs(request: Request):
    body = await request.json()
    mem.save_icpdb_prefs(body)
    return JSONResponse({"ok": True})


@app.get("/api/icpdb/stats")
async def get_icpdb_stats():
    audit = mem.get_last_icpdb_audit()
    runs = mem.load_icpdb_runs()
    last_run = runs[0] if runs else None
    return JSONResponse({
        "last_audit": audit,
        "last_run": {k: v for k, v in last_run.items() if k not in ("audit",)} if last_run else None,
    })


# ── Alegría session ───────────────────────────────────────────────────────────

class AlegriaSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.outbox:   queue.Queue[dict | None] = queue.Queue()
        self.msg_inbox: queue.Queue[str | None] = queue.Queue()  # blocking user replies
        self.interject_inbox: queue.Queue[str]  = queue.Queue()  # non-blocking interjections
        self.thread: threading.Thread | None = None

    def on_event(self, event: dict) -> None:
        self.outbox.put(event)

    def check_pause(self) -> str | None:
        try:
            return self.interject_inbox.get_nowait()
        except queue.Empty:
            return None

    def get_user_message(self) -> str | None:
        return self.msg_inbox.get()

    def start(self, fresh: bool = False) -> None:
        def _run():
            try:
                alegria_agent.run_with_callbacks(
                    on_event=self.on_event,
                    check_pause=self.check_pause,
                    get_user_message=self.get_user_message,
                    fresh=fresh,
                )
            except Exception as exc:
                self.outbox.put({"type": "error", "message": str(exc)})
            finally:
                self.outbox.put(None)

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()


# ── Alegría REST endpoints ────────────────────────────────────────────────────

@app.get("/api/alegria/history")
async def get_alegria_history():
    return JSONResponse(mem.get_alegria_history_for_display())


@app.post("/api/alegria/clear")
async def clear_alegria_history():
    mem.clear_alegria_history()
    return JSONResponse({"ok": True})


# ── Alegría WebSocket endpoint ────────────────────────────────────────────────

@app.websocket("/ws/alegria")
async def alegria_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session: AlegriaSession | None = None
    loop = asyncio.get_event_loop()

    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start'}"}))
            return

        fresh = bool(msg.get("fresh", False))
        session = AlegriaSession(ws)
        session.start(fresh=fresh)

        await ws.send_text(json.dumps({"type": "started"}))

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
                    t = ctrl.get("type")
                    if t == "message":
                        session.msg_inbox.put(ctrl.get("message", ""))
                    elif t == "interject":
                        session.interject_inbox.put(ctrl.get("message", ""))
                except WebSocketDisconnect:
                    session.msg_inbox.put(None)
                    break

        await asyncio.gather(_pump_outbox(), _receive_controls())

    except WebSocketDisconnect:
        if session:
            session.msg_inbox.put(None)
    except Exception as exc:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass


@app.get("/")
async def get_dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text())
