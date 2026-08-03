from typing import Any, Dict
from uuid import uuid4

from fastapi import HTTPException, Response

from src.constants import TOKEN_LENGTH, VERDICT_BANDS


def generate_token() -> str:
    """Return a run token. It becomes the session id and the report URL."""
    return uuid4().hex[:TOKEN_LENGTH]


def verdict_for(score: int) -> str:
    for ceiling, verdict in VERDICT_BANDS:
        if score <= ceiling:
            return verdict
    return VERDICT_BANDS[-1][1]


def make_response(
    response: Response,
    success: bool = True,
    message: str = "",
    data: Any = None,
    status_code: int = 200,
) -> Dict[str, Any]:
    if data is None:
        data = {}
    response.status_code = status_code
    if success is False:
        error = HTTPException(status_code=status_code, detail=message)
        setattr(error, "data", data)
        raise error
    return {"success": success, "message": message, "data": data}
