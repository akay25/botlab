"""Hold scored sessions in memory and append every one to a log.

The log is the record of the experiment. It keeps the raw telemetry as well as
the score, so a stored run can be re-scored later when the rules change. The
in-memory copy exists only so the dashboard can read the recent ones without
walking the file.
"""

import collections
import json
import os
import threading
from typing import Any, Dict, List, Optional

from .config import config
from .logging import get_logger

logger = get_logger("loaders.storage")

_LOCK = threading.Lock()
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_ORDER: List[str] = []

# A page visit waits here between the navigation that served the task page and
# the report that follows it. The navigation is the request worth scoring on
# the http layer; the report arrives later by fetch, whose headers describe a
# background request rather than the client.
_VISITS: "collections.OrderedDict[str, Dict[str, Any]]" = collections.OrderedDict()
MAX_PENDING_VISITS = 300


def remember_visit(token: str, visit: Dict[str, Any]) -> None:
    with _LOCK:
        _VISITS[token] = visit
        while len(_VISITS) > MAX_PENDING_VISITS:
            _VISITS.popitem(last=False)


def take_visit(token: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        return _VISITS.pop(token, None)


def save(session: Dict[str, Any]) -> None:
    """Keep the session in memory and append it to the log."""
    with _LOCK:
        if session["id"] not in _SESSIONS:
            _ORDER.append(session["id"])
        _SESSIONS[session["id"]] = session
        while len(_ORDER) > config.SESSION_CACHE_SIZE:
            _SESSIONS.pop(_ORDER.pop(0), None)

    os.makedirs(config.DATA_DIR, exist_ok=True)
    try:
        with open(config.log_file, "a") as handle:
            handle.write(json.dumps(session) + "\n")
    except OSError as error:
        logger.error("Could not append to the session log: %s", error)


def recent(limit: int = 60) -> List[Dict[str, Any]]:
    with _LOCK:
        ids = [i for i in reversed(_ORDER) if i in _SESSIONS]
        return [_SESSIONS[i] for i in ids[:limit]]


def find(session_id: str) -> Optional[Dict[str, Any]]:
    """Return one session, from memory first and then from the log."""
    with _LOCK:
        if session_id in _SESSIONS:
            return _SESSIONS[session_id]
    return _search_log(session_id)


def _search_log(session_id: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(config.log_file):
        return None
    found = None
    with open(config.log_file) as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("id") == session_id:
                found = record
    return found


def iter_log():
    """Yield every logged session, oldest first."""
    if not os.path.exists(config.log_file):
        return
    with open(config.log_file) as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except ValueError:
                continue
