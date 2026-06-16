import json

from ..db import execute
from ..security import redact_context


def log_event(level, message, context=None):
    safe_context = redact_context(context or {})
    execute(
        "INSERT INTO system_logs (level, message, context_json) VALUES (?, ?, ?)",
        (level.upper(), message, json.dumps(safe_context, ensure_ascii=False)),
    )
