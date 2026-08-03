from fastapi import APIRouter, Request, Response

from src.detection import session as session_service
from src.loaders import storage
from src.loaders.config import config
from src.loaders.logging import get_logger
from src.loaders.tls_proxy import lookup
from src.types.input.collect import CollectPayload
from src.utils import make_response

logger = get_logger("routes.collect")

router = APIRouter(
    prefix="/collect",
    tags=["collect"],
    responses={404: {"description": "Not found"}},
)


@router.post("")
async def collect(body: CollectPayload, request: Request, response: Response):
    """Score one report and store it.

    The task page posts the run token it was served along with the raw
    interaction telemetry. The token is what ties the report back to the
    navigation that served the page, which is the request worth scoring on
    the http layer.

    The reply carries the score and the two things the page cannot measure
    for itself: the TLS handshake and the address it came from.
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
    session_service.apply_payload(current, body)

    visit = storage.take_visit(body.session) if body.session else None
    session_service.adopt_page_visit(current, visit, body.session)

    result = session_service.score(current)
    storage.save(current)
    logger.info(
        "Scored %s as %s (%s), caught by %s",
        current["id"], result["score"], result["verdict"],
        result["first_catching_layer"],
    )

    return make_response(response, data={
        **result,
        "session_id": current["id"],
        "ip": current["ip"],
        "header_source": current.get("header_source"),
        "tls_measured": current.get("tls_measured"),
        "tls": current.get("tls"),
    })
