"""The dashboard web server — a thin shell around radiant/webdata.py.

Serves the single-page console and a small JSON API backed by the real index
and the events store. FastAPI/uvicorn are an optional extra
(`pip install -e ".[web]"`); the data functions in webdata.py stay usable and
tested without them.
"""

from __future__ import annotations

from pathlib import Path

from radiant import webdata

WEB_DIR = Path(__file__).parent / "web"


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
