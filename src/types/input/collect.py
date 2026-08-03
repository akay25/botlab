from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CapturedRequest(BaseModel):
    """The navigation the extension observed with chrome.webRequest.

    The extension reports over fetch, whose headers belong to a background
    request. The navigation is the one worth scoring, so the extension sends
    what it saw and the harness scores that instead.
    """

    url: Optional[str] = None
    order: List[str] = Field(default_factory=list)
    headers: Dict[str, str] = Field(default_factory=dict)


class CollectPayload(BaseModel):
    """One report from the task page or from the extension.

    The probe blocks stay loosely typed on purpose. They carry raw telemetry
    and raw probe output whose shape changes as detections are added, and the
    detection engine reads them defensively. Pinning a schema here would mean
    dropping fields a newer client sends.
    """

    # The run token the task page was served. Absent for extension reports.
    session: Optional[str] = None
    label: str = ""
    source: str = "extension"
    reason: str = ""
    page_url: str = ""

    js: Optional[Dict[str, Any]] = None
    runtime: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    behavior: Optional[Dict[str, Any]] = None
    extension: Optional[Dict[str, Any]] = None
    request: Optional[CapturedRequest] = None
