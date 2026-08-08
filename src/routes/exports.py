import csv
import io

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse

from src import profile as profile_service
from src.constants import CSV_COLUMNS, LAYERS
from src.loaders import storage
from src.loaders.logging import get_logger

logger = get_logger("routes.exports")

router = APIRouter(
    prefix="/export",
    tags=["export"],
    responses={404: {"description": "Not found"}},
)


def _row(record):
    result = record.get("result") or {}
    layers = result.get("layers") or {}
    ids = []
    for layer in LAYERS:
        ids += (layers.get(layer) or {}).get("ids") or []

    row = {
        "time": record.get("time", ""),
        "id": record.get("id", ""),
        "label": record.get("label", ""),
        "ip": record.get("ip", ""),
        "score": result.get("score", ""),
        "verdict": result.get("verdict", ""),
        "first_catching_layer": result.get("first_catching_layer", ""),
        "strongest_layer": result.get("strongest_layer", ""),
        "total_weight": result.get("total_weight", ""),
        "ja4": (record.get("tls") or {}).get("ja4", ""),
        "ja3": (record.get("tls") or {}).get("ja3", ""),
        "user_agent": (record.get("headers") or {}).get("user-agent", ""),
        "detection_ids": " ".join(ids),
        "source": record.get("source", ""),
        "header_source": record.get("header_source", ""),
        "page_url": record.get("page_url", ""),
    }
    for layer in LAYERS:
        row["w_" + layer] = (layers.get(layer) or {}).get("weight", 0)
    return row


@router.get("/profile/{session_id}.json")
async def export_profile(session_id: str, name: str = "",
                         voice_type: str = profile_service.DEFAULT_VOICE_TYPE):
    """Return one run as a bare replay profile, ready to hand to another program.

    Bare on purpose: no envelope, no notes, nothing a consumer has to unwrap.
    `curl .../api/export/profile/<id>.json > profile.json` writes a file that
    is already the input format.

    /api/sessions/{id}/profile returns the same document with the list of
    fields no measurement backed, which is the one worth reading first.
    """
    record = storage.find(session_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No session has that id.")
    built = profile_service.build(record, name=name or None, voice_type=voice_type)
    return JSONResponse(built, headers={
        "Content-Disposition": 'attachment; filename="botlab-profile-%s.json"'
                               % built["name"],
    })


@router.get(".csv", response_class=PlainTextResponse)
async def export_csv():
    """Return every logged session as CSV, one row per run.

    This is the table an analysis starts from. It carries the per-layer
    weights and the detection IDs, not only the score, because a score is one
    number a reader cannot check.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for record in storage.iter_log():
        writer.writerow(_row(record))
    return PlainTextResponse(buffer.getvalue(), media_type="text/csv; charset=utf-8")
