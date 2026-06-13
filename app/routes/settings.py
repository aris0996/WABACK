from flask import Blueprint, jsonify, request
from ..middleware.auth_required import auth_required
from ..services.settings_service import get_settings, update_settings
from ..services.relay_client import relay_client

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
