from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """One piece of evidence about a session."""

    layer: str
    id: str
    weight: float
    detail: str


class LayerResult(BaseModel):
    """What one layer concluded."""

    weight: float
    count: int
    ids: List[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    """The verdict and the evidence behind it."""

    score: int = Field(..., ge=1, le=99, description="1 is automated, 99 is human.")
    verdict: str
    total_weight: float
    first_catching_layer: Optional[str] = Field(
        None, description="The earliest layer in the stack that flagged the client.")
    strongest_layer: Optional[str] = None
    layers: Dict[str, LayerResult] = Field(default_factory=dict)
    signals: List[Signal] = Field(default_factory=list)
    # Derived pointer and keystroke figures. Open by design: the shape grows
    # as detections are added, and the report renders whatever arrives.
    behavior_metrics: Optional[Dict[str, Any]] = None


class CollectResult(ScoreResult):
    """A score plus the two things only the harness can tell the client."""

    session_id: str
    ip: Optional[str] = None
    header_source: Optional[str] = None
    tls: Optional[Dict[str, Any]] = None


class SessionSummary(BaseModel):
    """One row of the dashboard."""

    id: str
    time: str
    label: str = ""
    ip: str = ""
    source: str = ""
    page_url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    tls: Optional[Dict[str, Any]] = None
    result: Optional[ScoreResult] = None
