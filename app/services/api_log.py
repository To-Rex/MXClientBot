"""In-memory log of 1C HTTP-service calls, shown in the admin panel (/panel/api-logs).

A bounded ring buffer per process: the newest MAX_ENTRIES calls (request URL,
headers-safe summary, body, response, status, duration). No disk writes — the
log resets on restart, which is fine for a debugging view.
"""
import itertools
import json
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

MAX_ENTRIES = 300
_BODY_LIMIT = 4000  # chars kept per body/response

_entries: deque = deque(maxlen=MAX_ENTRIES)
_seq = itertools.count(1)
_lock = threading.Lock()


def _clip(value: Any) -> Any:
    """Keep payloads readable and bounded."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    if len(text) > _BODY_LIMIT:
        return text[:_BODY_LIMIT] + f"… [{len(text) - _BODY_LIMIT} belgi qisqartirildi]"
    return text


def record(
    *,
    endpoint: str,
    method: str,
    url: str,
    params: Optional[dict] = None,
    request_body: Optional[dict] = None,
    status_code: Optional[int] = None,
    response_body: Any = None,
    outcome: str = "ok",           # ok | error | unavailable
    error: str = "",
    duration_ms: Optional[float] = None,
    expected: Any = None,          # docs-based expected response shape (for diff view)
) -> None:
    entry = {
        "id": next(_seq),
        "time": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "method": method.upper(),
        "url": url,
        "params": _clip(params) if params else None,
        "request_body": _clip(request_body) if request_body is not None else None,
        "status_code": status_code,
        "response_body": _clip(response_body),
        "outcome": outcome,
        "error": error[:500] if error else "",
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "expected": _clip(expected) if expected is not None else None,
    }
    with _lock:
        _entries.append(entry)


def amend_last(endpoint: str, outcome: str, error: str = "", expected: Any = None) -> None:
    """Mark the newest entry for *endpoint* (e.g. shape validation failed after a 200)."""
    with _lock:
        for e in reversed(_entries):
            if e["endpoint"] == endpoint:
                e["outcome"] = outcome
                if error:
                    e["error"] = error[:500]
                if expected is not None:
                    e["expected"] = _clip(expected)
                break


def entries(limit: int = MAX_ENTRIES, endpoint: str = "", outcome: str = "", after_id: int = 0) -> list[dict]:
    """Newest first, optionally filtered."""
    with _lock:
        items = list(_entries)
    if after_id:
        items = [e for e in items if e["id"] > after_id]
    if endpoint:
        items = [e for e in items if e["endpoint"] == endpoint]
    if outcome:
        items = [e for e in items if e["outcome"] == outcome]
    items.reverse()
    return items[:limit]


def known_endpoints() -> list[str]:
    with _lock:
        return sorted({e["endpoint"] for e in _entries})


def stats() -> dict:
    with _lock:
        items = list(_entries)
    return {
        "total": len(items),
        "ok": sum(1 for e in items if e["outcome"] == "ok"),
        "error": sum(1 for e in items if e["outcome"] == "error"),
        "unavailable": sum(1 for e in items if e["outcome"] == "unavailable"),
    }


def clear() -> None:
    with _lock:
        _entries.clear()
