import csv
import io

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

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
