from typing import Any, Dict, Optional

from pydantic import BaseModel


class CollectPayload(BaseModel):
    """One report from the task page.

    The probe blocks stay loosely typed on purpose. They carry raw telemetry
    and raw probe output whose shape changes as detections are added, and the
    detection engine reads them defensively. Pinning a schema here would mean
    dropping fields a newer page sends.
    """

    # The run token the page was served. It becomes the session id, which is
    # how the page can link to its own report before the report exists.
    session: Optional[str] = None
    label: str = ""
    source: str = "page"
    reason: str = ""
    page_url: str = ""

    js: Optional[Dict[str, Any]] = None
    runtime: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    behavior: Optional[Dict[str, Any]] = None
