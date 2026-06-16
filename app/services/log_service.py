import json
import time

from flask import current_app

from ..db import execute
from ..security import redact_context

_throttle = {}


def log_event(level, message, context=None):
    safe_context = redact_context(context or {})
    execute(
        "INSERT INTO system_logs (level, message, context_json) VALUES (?, ?, ?)",
        (level.upper(), message, json.dumps(safe_context, ensure_ascii=False)),
    )
    cleanup_old_logs()


def log_event_throttled(level, message, context=None, key=None, window_seconds=60):
    now = time.time()
    throttle_key = key or f"{level}:{message}"
    previous = _throttle.get(throttle_key, 0)
    if now - previous < window_seconds:
        return False
    _throttle[throttle_key] = now
    log_event(level, message, context)
    return True


def cleanup_old_logs():
    now = time.time()
    previous = _throttle.get("log-cleanup", 0)
    if now - previous < 3600:
        return
    _throttle["log-cleanup"] = now
    days = current_app.config.get("LOG_RETENTION_DAYS", 14)
    execute("DELETE FROM system_logs WHERE created_at < datetime('now', ?)", (f"-{days} days",))
