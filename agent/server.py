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
from . import tasks
from .luzia_agent import run_with_callbacks
from . import kooza_agent
from . import alegria_agent
from . import varekai_agent
from . import kurios_agent

app = FastAPI(title="Contortion Space Agent Dashboard")

# Serve generated images at /output/...
_output_dir = Path(__file__).parent.parent / "output"
_output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_output_dir)), name="output")


# ── Agent session (shared by Luzia / Kooza / Varekai) ────────────────────────

class Session:
    """One running agent thread bridged to one WebSocket.

    All human-in-the-loop decisions flow through a single queue: the agent
    calls decide(kind, payload), which emits {"type": kind, **payload} to the
    dashboard and blocks until a decision message arrives. On disconnect a
    None sentinel unblocks the thread (the runtime raises DecisionAborted).
    """

    def __init__(self):
        self.outbox:         queue.Queue[dict | None] = queue.Queue()
        self.inbox:          queue.Queue[str]         = queue.Queue()  # interjections
        self.decision_inbox: queue.Queue              = queue.Queue()
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

    def decide(self, kind: str, payload: dict):
        self.outbox.put({"type": kind, **payload})
        return self.decision_inbox.get()

    def abort_pending_decision(self) -> None:
        self.decision_inbox.put(None)

    def start(self, target) -> None:
        def _run():
            try:
                target()
            except Exception as exc:
                self.outbox.put({"type": "error", "message": str(exc)})
            finally:
                self.outbox.put(None)

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()


# Legacy WS message types from the dashboard, mapped to decision values.
_DECISION_MESSAGES = {
    "performer_decisions":   lambda c: {"decisions": c.get("decisions", [])},
    "update_decisions":      lambda c: {"decisions": c.get("decisions", [])},
    "dedup_decisions":       lambda c: {"decisions": c.get("decisions", [])},
    "user_input":            lambda c: c.get("message", ""),
    "photo_urls":            lambda c: c.get("urls", {}),
    "eligibility_decisions": lambda c: {
        "confirmed_ids": c.get("confirmed_ids", []),
        "sent_ids":      c.get("sent_ids", []),
        "skipped_ids":   c.get("skipped_ids", []),
    },
    "reply_decisions":       lambda c: c.get("replies", []),
    "decision_response":     lambda c: c.get("data"),
}


async def _serve_agent(ws: WebSocket, session: Session, target) -> None:
    """Pump agent events to the socket and route control messages back."""
    loop = asyncio.get_event_loop()
    session.start(target)

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
                if t in _DECISION_MESSAGES:
                    session.decision_inbox.put(_DECISION_MESSAGES[t](ctrl))
                elif t == "interject":
                    session.inbox.put(ctrl.get("message", ""))
                elif t == "pause":
                    session.pause_requested.set()
                elif t == "resume":
                    session.inbox.put(ctrl.get("message", ""))
                elif t == "outreach_sent":
                    # Varekai send queue: record a sent DM in Notion immediately
                    page_id = ctrl.get("page_id", "")
                    if page_id:
                        from .varekai_tools import record_outreach_sent
                        await loop.run_in_executor(None, record_outreach_sent, page_id)
                        await ws.send_text(json.dumps({"type": "outreach_sent_ack", "page_id": page_id}))
            except WebSocketDisconnect:
                session.abort_pending_decision()
                break

    await asyncio.gather(_pump_outbox(), _receive_controls())


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@app.websocket("/ws")
async def luzia_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        msg = json.loads(await ws.receive_text())
        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start', month:'...'}"}))
            return
        month_label = msg.get("month", "").strip()
        if not month_label:
            await ws.send_text(json.dumps({"type": "error", "message": "month is required"}))
            return

        cfg.set_overrides(msg.get("db_config", {}))
        replay_from   = int(msg.get("replay_from", 1))
        replay_run_id = msg.get("replay_run_id")
        cached_run    = mem.get_run(replay_run_id) if replay_run_id else None

        session = Session()
        await ws.send_text(json.dumps({"type": "started", "month": month_label,
                                       "replay_from": replay_from}))
        await _serve_agent(ws, session, lambda: run_with_callbacks(
            month_label=month_label,
            on_event=session.on_event,
            check_pause=session.check_pause,
            decide=session.decide,
            run_id=replay_run_id,
            replay_from=replay_from,
            cached_run=cached_run,
        ))
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


@app.post("/api/upload-performer-photo")
async def upload_performer_photo(request: Request):
    """Accept {filename, data_b64} JSON, upload to Webflow Assets, return CDN URL."""
    import base64
    import tempfile
    from pathlib import Path as _Path
    from .compositor import upload_to_webflow

    body = await request.json()
    filename = body.get("filename", "performer-photo.jpg")
    data_b64 = body.get("data_b64", "")

    try:
        data = base64.b64decode(data_b64)
    except Exception:
        return JSONResponse({"error": "invalid base64"}, status_code=400)

    suffix = _Path(filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = _Path(tmp.name)

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, upload_to_webflow, tmp_path, filename
        )
        return JSONResponse({"url": result["url"]})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        tmp_path.unlink(missing_ok=True)


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

# ── ICPDB (Kooza) WebSocket endpoint ──────────────────────────────────────────

@app.websocket("/ws/icpdb")
async def icpdb_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        msg = json.loads(await ws.receive_text())
        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start', run_mode:'...'}"}))
            return

        run_mode = msg.get("run_mode", "full")
        prefs = mem.get_icpdb_prefs()
        session = Session()
        await ws.send_text(json.dumps({"type": "started", "run_mode": run_mode}))
        await _serve_agent(ws, session, lambda: kooza_agent.run_with_callbacks(
            on_event=session.on_event,
            check_pause=session.check_pause,
            decide=session.decide,
            run_mode=run_mode,
            prefs=prefs,
        ))
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


@app.get("/api/tasks")
async def get_tasks():
    """All recurring tasks (monthly roundup, quarterly outreach, ICPDB health)."""
    return JSONResponse(tasks.get_tasks())


@app.get("/api/activity")
async def get_activity(limit: int = 10):
    """Most recent completed runs across all agents, for the home activity feed."""
    from . import run_store
    with run_store._connect() as conn:
        rows = conn.execute(
            "SELECT agent, data FROM runs WHERE status = 'completed' "
            "ORDER BY completed_at DESC LIMIT ?",
            (max(1, min(limit, 50)),),
        ).fetchall()
    out = []
    for agent, data in rows:
        record = json.loads(data)
        record["agent"] = agent
        out.append(record)
    return JSONResponse(out)


@app.get("/api/varekai/due")
async def get_varekai_due():
    t = next((t for t in tasks.get_tasks() if t["agent"] == "varekai"), {})
    return JSONResponse({
        "due":             t.get("due", True),
        "days_since_last": t.get("days_since_last"),
        "next_due_in":     t.get("next_due_in", 0),
        "last_run_date":   t.get("last_run_date"),
    })


# ── Varekai WebSocket endpoint ────────────────────────────────────────────────

@app.websocket("/ws/varekai")
async def varekai_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        msg = json.loads(await ws.receive_text())
        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start', run_mode:'...'}"}))
            return

        run_mode = msg.get("run_mode", "full")
        session = Session()
        await ws.send_text(json.dumps({"type": "started", "run_mode": run_mode}))
        await _serve_agent(ws, session, lambda: varekai_agent.run_with_callbacks(
            run_mode=run_mode,
            on_event=session.on_event,
            check_pause=session.check_pause,
            decide=session.decide,
        ))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass


# ── Kurios WebSocket + API ────────────────────────────────────────────────────

@app.websocket("/ws/kurios")
async def kurios_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        msg = json.loads(await ws.receive_text())
        if msg.get("type") != "start":
            await ws.send_text(json.dumps({"type": "error", "message": "First message must be {type:'start'}"}))
            return

        session = Session()
        await ws.send_text(json.dumps({"type": "started"}))
        await _serve_agent(ws, session, lambda: kurios_agent.run_with_callbacks(
            on_event=session.on_event,
            check_pause=session.check_pause,
        ))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass


@app.get("/api/kurios/jobs")
async def get_kurios_jobs():
    """Current active job listings from the Notion jobs database."""
    from .kurios_tools import list_active_jobs
    try:
        return JSONResponse(list_active_jobs())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/kurios/sources")
async def get_kurios_sources():
    """Job sources with listing counts from the Job Sources Notion database."""
    from .kurios_tools import list_job_sources
    try:
        return JSONResponse(list_job_sources())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Daily scheduler ───────────────────────────────────────────────────────────

def _start_scheduler():
    """
    Run a lightweight background scheduler in its own daemon thread.
    Checks every hour whether any tasks are due; if so, runs them silently
    (no WebSocket — autonomous mode, output goes to server logs only).
    The scheduler is intentionally simple: APScheduler is not required.
    """
    import time as _time

    def _run_kurios_headless():
        import logging
        log = logging.getLogger("kurios.scheduler")
        try:
            log.info("Scheduler: starting Kurios jobs scan")
            result = kurios_agent.run_with_callbacks(
                on_event=lambda e: log.debug("kurios event %s", e),
            )
            status = result.get("status", "unknown")
            log.info("Scheduler: Kurios finished — %s", status)
        except Exception as exc:
            log.error("Scheduler: Kurios failed — %s", exc)

    def _loop():
        while True:
            _time.sleep(3600)   # check once per hour
            try:
                due_tasks = tasks.get_due_tasks()
                for t in due_tasks:
                    if t["id"] == "circus_jobs_scan":
                        _run_kurios_headless()
            except Exception:
                pass

    t = threading.Thread(target=_loop, daemon=True, name="kurios-scheduler")
    t.start()


# Start the scheduler when the server process boots
_start_scheduler()


@app.get("/")
async def get_dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text())
