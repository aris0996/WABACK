from flask import Blueprint, jsonify, request
from ..middleware.auth_required import auth_required
from ..services.settings_service import get_settings, update_settings
from ..services.relay_client import relay_client
from ..services.waha_service import waha_service

settings_bp = Blueprint("settings", __name__)


@settings_bp.get("")
@auth_required
def index():
    return jsonify(get_settings())


@settings_bp.put("")
@auth_required
def update():
    settings = update_settings(request.get_json(silent=True) or {})
    relay_client.send_event(settings.get("relay_flutter_target_device_id"), "settings_updated", {"settings": settings})
    return jsonify(settings)


@settings_bp.get("/test-waha")
@auth_required
def test_waha():
    try:
        chats = waha_service.get_chats(limit=1, offset=0)
        return jsonify({"ok": True, "message": "WAHA bisa diakses dari backend", "sample_count": len(chats), "sample": chats[:1]})
    except Exception as exc:
        return jsonify({"ok": False, "error": "waha_test_failed", "message": str(exc)}), 502
