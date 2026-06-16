import hmac

from flask import Blueprint, current_app, jsonify, request

from ..services.log_service import log_event
from ..services.update_service import auto_update, get_git_status

update_bp = Blueprint("update", __name__, url_prefix="/webhook")


def _valid_github_signature(raw_body):
    secret = current_app.config["GITHUB_WEBHOOK_SECRET"]
    if not secret:
        return True
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, "sha256").hexdigest()
    return hmac.compare_digest(signature, expected)


def _valid_update_key():
    api_key = current_app.config["AUTO_UPDATE_API_KEY"]
    if not api_key:
        return True
    provided = request.headers.get("X-Update-Key") or request.headers.get("X-Api-Key") or ""
    return hmac.compare_digest(provided, api_key)


def _auth_configured():
    return bool(current_app.config["GITHUB_WEBHOOK_SECRET"] or current_app.config["AUTO_UPDATE_API_KEY"])


@update_bp.post("/github")
def github_update():
    raw_body = request.get_data() or b""
    if not _auth_configured():
        return jsonify({"ok": False, "error": "GitHub auto update auth is not configured"}), 503
    if not _valid_update_key():
        log_event("WARNING", "GitHub update rejected: invalid API key", {})
        return jsonify({"ok": False, "error": "Invalid update API key"}), 401
    if not _valid_github_signature(raw_body):
        log_event("WARNING", "GitHub update rejected: invalid signature", {})
        return jsonify({"ok": False, "error": "Invalid GitHub signature"}), 401

    payload = request.get_json(silent=True) or {}
    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return jsonify({"ok": True, "message": "pong"})

    configured_branch = current_app.config["AUTO_UPDATE_BRANCH"].strip()
    ref = payload.get("ref", "")
    if configured_branch and ref and not ref.endswith(f"/{configured_branch}"):
        return jsonify({"ok": True, "ignored": True, "reason": f"Ref {ref} is not {configured_branch}"})

    try:
        result = auto_update()
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        context = {
            "event": event,
            "ref": ref,
            "error": str(exc),
            "status": get_git_status(),
        }
        log_event("ERROR", "GitHub auto update failed", context)
        return jsonify({"ok": False, "error": str(exc)}), 409


@update_bp.get("/github/status")
def github_update_status():
    if not _auth_configured():
        return jsonify({"ok": False, "error": "GitHub auto update auth is not configured"}), 503
    if not current_app.config["AUTO_UPDATE_API_KEY"]:
        return jsonify({"ok": False, "error": "Status endpoint requires AUTO_UPDATE_API_KEY"}), 403
    if not _valid_update_key():
        return jsonify({"ok": False, "error": "Invalid update API key"}), 401
    try:
        return jsonify({"ok": True, "status": get_git_status()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
