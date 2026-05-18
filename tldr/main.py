from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

from tldr.web.routes import articles, dashboard, inbox, reports, search, settings as settings_routes
from tldr.web.templates import templates  # noqa: F401  (imports template env)

app = FastAPI(title="TLDRDigest", version="0.1.0")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")

app.include_router(dashboard.router)
app.include_router(inbox.router)
app.include_router(articles.router)
app.include_router(search.router)
app.include_router(reports.router)
app.include_router(settings_routes.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")
