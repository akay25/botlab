from fastapi import APIRouter, Request, Response, status

from src import profile as profile_service
from src.detection import session as session_service
from src.loaders import storage
from src.loaders.config import config
from src.loaders.logging import get_logger
from src.loaders.tls_proxy import lookup
from src.utils import make_response

logger = get_logger("routes.sessions")

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    responses={404: {"description": "Not found"}},
)


@router.get("")
async def list_sessions(response: Response, limit: int = 60):
    """Return the most recently scored sessions, newest first."""
    rows = storage.recent(max(1, min(limit, 200)))
    return make_response(response, data={"sessions": rows, "count": len(rows)})


@router.get("/{session_id}")
async def get_session(session_id: str, response: Response):
    """Return one scored session, with its raw telemetry and probe output."""
    record = storage.find(session_id)
    if record is None:
        return make_response(
            response,
            success=False,
            message="No session has that id.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return make_response(response, data=record)


@router.get("/{session_id}/profile")
async def get_profile(session_id: str, response: Response, name: str = "",
                      voice_type: str = profile_service.DEFAULT_VOICE_TYPE):
    """Return the run rewritten as a replay profile, with its gaps listed.

    The profile is the run pointed the other way: what another client would
    have to report to look like this one. `gaps` names every field no
    measurement backed, because the profile itself cannot show which of its
    values were read and which were filled in.

    /api/export/profile/{id}.json returns the same profile as a bare file for
    a program to consume.
    """
    record = storage.find(session_id)
    if record is None:
        return make_response(
            response,
            success=False,
            message="No session has that id.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    built, gaps = profile_service.describe(record, name=name or None,
                                           voice_type=voice_type)
    return make_response(response, data={"profile": built, "gaps": gaps})


probe_router = APIRouter(
    prefix="/probe",
    tags=["probe"],
    responses={404: {"description": "Not found"}},
)


@probe_router.get("")
async def probe(request: Request, response: Response, label: str = ""):
    """Score the caller itself.

    A non-browser client runs no JavaScript, so this reaches the network, tls,
    http and consistency layers only. It is how curl, urllib and the client
    matrix enter the results table.
    """
    peer = request.client
    handshake = lookup(peer.port if peer else None)

    current = session_service.new_session(
        client_ip=handshake.get("ip") or (peer.host if peer else ""),
        headers=dict(request.headers),
        header_order=[name for name, _ in request.headers.items()],
        path=str(request.url.path),
        tls=handshake.get("tls"),
        tls_measured=config.TLS_ENABLED and bool(handshake),
    )
    current["label"] = label[:60]
    current["source"] = "probe"

    session_service.score(current)
    storage.save(current)
    return make_response(response, data=current)
