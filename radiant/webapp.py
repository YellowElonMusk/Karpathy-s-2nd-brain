"""The dashboard web server — a thin shell around radiant/webdata.py.

Serves the single-page console and a small JSON API backed by the real index
and the events store. FastAPI/uvicorn are an optional extra
(`pip install -e ".[web]"`); the data functions in webdata.py stay usable and
tested without them.
"""

from __future__ import annotations

from pathlib import Path

from radiant import events as events_mod, webdata

WEB_DIR = Path(__file__).parent / "web"

# Module-level so the `request: Request` annotation resolves under
# `from __future__ import annotations` (otherwise FastAPI can't see the type
# and treats it as a query param). None when FastAPI isn't installed.
try:
    from fastapi import Request
except Exception:  # pragma: no cover - optional dependency
    Request = None


def create_app(root: Path):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse
    except ImportError as e:
        raise RuntimeError(
            "the dashboard needs FastAPI — install with: pip install -e \".[web]\""
        ) from e

    app = FastAPI(title="RadiantBrain Console", docs_url=None, redoc_url=None)

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/graph")
    def graph():
        try:
            return JSONResponse(webdata.graph_json(root))
        except FileNotFoundError as e:
            raise HTTPException(503, str(e))

    @app.get("/api/page/{slug}")
    def page(slug: str):
        try:
            data = webdata.page_json(root, slug)
        except FileNotFoundError as e:
            raise HTTPException(503, str(e))
        if data is None:
            raise HTTPException(404, f"no page {slug!r}")
        return JSONResponse(data)

    @app.get("/api/events")
    def events():
        return JSONResponse(webdata.events_json(root))

    @app.post("/api/events")
    async def ingest(request: Request):
        # Optional bearer token — required only if RADIANT_INGEST_TOKEN is set,
        # so local agents work out of the box and remote agents can be secured.
        import os

        token = os.environ.get("RADIANT_INGEST_TOKEN")
        if token:
            auth = request.headers.get("authorization", "")
            if auth.removeprefix("Bearer ").strip() != token:
                raise HTTPException(401, "bad or missing ingest token")
        payload = await request.json()
        rows = payload.get("events", payload) if isinstance(payload, dict) else payload
        if isinstance(rows, dict):
            rows = [rows]
        created, errors = [], []
        for r in rows:
            try:
                created.append(events_mod.add_event(root, events_mod.normalize_event(r)))
            except events_mod.NormalizeError as e:
                errors.append(str(e))
        return JSONResponse({"created": created, "errors": errors},
                            status_code=207 if errors else 201)

    @app.post("/api/sync")
    def sync():
        """One-shot feed sync: pull new Telegram messages if the reader is
        configured (RADIANT_TELEGRAM_TOKEN/CHAT), else just a no-op the client
        follows with a re-fetch. Suits a weekly-cron cadence — no polling."""
        import os

        token = os.environ.get("RADIANT_TELEGRAM_TOKEN")
        chat = os.environ.get("RADIANT_TELEGRAM_CHAT")
        if not (token and chat):
            return JSONResponse({"telegram": "not configured", "created": 0, "errors": []})
        from radiant import telegram

        try:
            created, errors = telegram.poll_once(root, token, chat)
        except Exception as e:
            return JSONResponse({"telegram": f"error: {e}", "created": 0, "errors": []},
                                status_code=502)
        return JSONResponse({"telegram": "ok", "created": len(created), "errors": errors})

    @app.get("/api/report/{event_id}")
    def report(event_id: int):
        data = webdata.report_json(root, event_id)
        if data is None:
            raise HTTPException(404, f"no event {event_id}")
        return JSONResponse(data)

    return app


def serve(root: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError(
            "the dashboard needs uvicorn — install with: pip install -e \".[web]\""
        ) from e
    app = create_app(root)
    print(f"RadiantBrain console → http://{host}:{port}  (Ctrl-C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
