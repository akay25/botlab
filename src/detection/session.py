"""Assemble the record that gets scored.

This module stays free of the web framework. The routes pull the pieces off
the request and hand them here as plain values, so a session can also be built
from a replayed log line.
"""

import datetime
from typing import Any, Dict, List, Optional

from src.utils import generate_token

from . import scoring


def new_session(
    client_ip: str,
    headers: Dict[str, str],
    header_order: List[str],
    path: str = "",
    tls: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a session from one connection and its request headers."""
    return {
        "id": session_id or generate_token(),
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "ip": client_ip,
        "path": path,
        "headers": {name.lower(): value for name, value in headers.items()},
        "header_order": [name.lower() for name in header_order],
        "tls": tls,
        "js": None,
        "runtime": None,
        "environment": None,
        "behavior": None,
        "extension": None,
        "source": "probe",
        "label": "",
        "header_source": "transport",
    }


def adopt_page_visit(session: Dict[str, Any], visit: Optional[Dict[str, Any]],
                     token: Optional[str]) -> bool:
    """Score a task-page run on its navigation, not on the report fetch.

    The page reports with `fetch`, whose headers belong to a background
    request and describe nothing about the client. The navigation that served
    the page is the request worth reading, and the token ties the two
    together. The token also becomes the session id, so the page can link to
    its own report before the report exists.
    """
    if not visit or not token:
        return False
    session["id"] = token
    session["transport_headers"] = session["headers"]
    session["transport_header_order"] = session["header_order"]
    session["headers"] = visit["headers"]
    session["header_order"] = visit["order"]
    session["header_source"] = "navigation"
    session["ip"] = visit.get("ip") or session["ip"]
    if visit.get("tls") and not session.get("tls"):
        session["tls"] = visit["tls"]
    return True


def adopt_captured_request(session: Dict[str, Any], captured) -> None:
    """Score an extension run on the navigation it captured for us.

    Keep the report's own headers beside it, because the connection they
    arrived on is what carried the TLS handshake.
    """
    order = getattr(captured, "order", None) or []
    if order:
        session["transport_headers"] = session["headers"]
        session["transport_header_order"] = session["header_order"]
        session["headers"] = {name.lower(): value
                              for name, value in (captured.headers or {}).items()}
        session["header_order"] = [str(name).lower() for name in order]
        session["header_source"] = "navigation"
    elif session.get("source") == "extension":
        # Nothing was captured, usually because the tab loaded before the
        # extension did. Say so rather than score the wrong request.
        session["header_source"] = "unavailable"


def apply_payload(session: Dict[str, Any], payload) -> None:
    """Copy the reported blocks onto the session."""
    session["js"] = payload.js
    session["runtime"] = payload.runtime
    session["environment"] = payload.environment
    session["behavior"] = payload.behavior
    session["extension"] = payload.extension
    session["source"] = payload.source
    session["label"] = payload.label
    session["page_url"] = payload.page_url
    session["reason"] = payload.reason


def score(session: Dict[str, Any]) -> Dict[str, Any]:
    session["result"] = scoring.evaluate(session)
    return session["result"]
