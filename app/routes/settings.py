from flask import Blueprint, jsonify, request
from ..middleware.auth_required import auth_required
from ..services.settings_service import get_settings, update_settings
from ..services.relay_client import relay_client
from ..services.waha_service import waha_service
from ..services.ollama_service import ollama_service
from ..extensions import db
from ..models import MessageLog

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
        db.session.add(MessageLog(direction="out", chat_id="system:waha", message="Test WAHA connection", status="ok"))
        db.session.commit()
        return jsonify({"ok": True, "message": "WAHA bisa diakses dari backend", "sample_count": len(chats), "sample": chats[:1]})
    except Exception as exc:
        db.session.add(MessageLog(direction="out", chat_id="system:waha", message="Test WAHA connection", status="error", error=str(exc)))
        db.session.commit()
        return jsonify({"ok": False, "error": "waha_test_failed", "message": str(exc)}), 502


@settings_bp.get("/ollama-models")
@auth_required
def ollama_models():
    settings = get_settings()
    try:
        return jsonify({"ok": True, "models": ollama_service.list_models(settings["ollama_base_url"])})
    except Exception as exc:
        db.session.add(MessageLog(direction="out", chat_id="system:ollama", message="List Ollama models", status="error", error=str(exc)))
        db.session.commit()
        return jsonify({"ok": False, "error": "ollama_models_failed", "message": str(exc), "models": []}), 502


@settings_bp.get("/test-ollama")
@auth_required
def test_ollama():
    settings = get_settings()
    try:
        response = ollama_service.generate(
            "Balas hanya dengan kata: OK",
            settings["ollama_model"],
            settings["ollama_temperature"],
            False,
            settings["ollama_base_url"],
        )
        db.session.add(MessageLog(direction="out", chat_id="system:ollama", message=f"Test Ollama model {settings['ollama_model']}", status="ok"))
        db.session.commit()
        return jsonify({"ok": True, "message": "Ollama terhubung dan bisa generate", "response": response})
    except Exception as exc:
        db.session.add(MessageLog(direction="out", chat_id="system:ollama", message=f"Test Ollama model {settings.get('ollama_model')}", status="error", error=str(exc)))
        db.session.commit()
        return jsonify({"ok": False, "error": "ollama_test_failed", "message": str(exc)}), 502
