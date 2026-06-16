import re
import time
from functools import wraps

from flask import jsonify, redirect, request, session, url_for


WA_NUMBER_RE = re.compile(r"^\+?[0-9]{7,20}$")
_webhook_hits = {}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Unauthorized"}), 401
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)

    return wrapper


def validate_wa_number(number):
    if not number:
        return False
    clean = str(number).replace("@c.us", "").replace("@s.whatsapp.net", "")
    return bool(WA_NUMBER_RE.match(clean))


def normalize_wa_number(number):
    return str(number or "").replace("@c.us", "").replace("@s.whatsapp.net", "").strip()


def require_json():
    if not request.is_json:
        return None, (jsonify({"ok": False, "error": "JSON body required"}), 400)
    data = request.get_json(silent=True)
    if data is None:
        return None, (jsonify({"ok": False, "error": "Invalid JSON"}), 400)
    return data, None


def webhook_rate_limited(limit=90, window=60):
    now = time.time()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0]
    hits = [hit for hit in _webhook_hits.get(ip, []) if now - hit < window]
    hits.append(now)
    _webhook_hits[ip] = hits
    return len(hits) > limit


def redact_context(context):
    if not isinstance(context, dict):
        return context
    hidden = {}
    for key, value in context.items():
        lowered = str(key).lower()
        if any(word in lowered for word in ("password", "token", "api_key", "secret")):
            hidden[key] = "[redacted]"
        else:
            hidden[key] = value
    return hidden
