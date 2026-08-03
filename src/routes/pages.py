"""The browser-facing pages. These sit outside the /api prefix."""

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from src.loaders import storage
from src.loaders.config import config
from src.loaders.logging import get_logger
from src.loaders.tls_proxy import lookup
from src.utils import generate_token

logger = get_logger("routes.pages")

router = APIRouter(tags=["pages"])


def _read_static(name: str):
    path = os.path.join(config.static_dir, os.path.basename(name))
    if not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()


def _missing(name: str) -> Response:
    logger.error("Static asset %s is missing", name)
    return PlainTextResponse("%s is missing." % name, status_code=404)


@router.get("/", response_class=HTMLResponse)
async def task_page(request: Request):
    """Serve the interaction test and remember the navigation that asked for it.

    The token handed to the page becomes the session id when the page reports
    back, so the report URL is known before the report exists. Remembering the
    navigation here is what lets the http layer read a real top-level request
    rather than the background fetch the page reports with.
    """
    page = _read_static("index.html")
    if page is None:
        return _missing("index.html")

    peer = request.client
    handshake = lookup(peer.port if peer else None)
    token = generate_token()
    storage.remember_visit(token, {
        "headers": {name.lower(): value for name, value in request.headers.items()},
        "order": [name.lower() for name, _ in request.headers.items()],
        "tls": handshake.get("tls"),
        "ip": handshake.get("ip") or (peer.host if peer else ""),
    })
    return HTMLResponse(page.decode().replace("__SESSION_ID__", token))


@router.get("/collector.js")
async def collector_script():
    body = _read_static("collector.js")
    if body is None:
        return _missing("collector.js")
    return Response(body, media_type="application/javascript; charset=utf-8")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    page = _read_static("dashboard.html")
    if page is None:
        return _missing("dashboard.html")
    return HTMLResponse(page.decode())


@router.get("/report/{session_id}", response_class=HTMLResponse)
async def report(session_id: str):
    """Serve the report viewer. It fetches the run itself from the API."""
    page = _read_static("report.html")
    if page is None:
        return _missing("report.html")
    return HTMLResponse(page.decode())
