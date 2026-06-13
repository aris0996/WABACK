from datetime import datetime
from flask import Blueprint, jsonify, request
from ..extensions import db
from ..models import Message, MessageLog
from ..services.ai_service import handle_auto_reply, serialize_message
from ..services.relay_client import relay_client
from ..services.settings_service import get_settings

webhook_bp = Blueprint("webhook", __name__)


def _get(payload, *keys):
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_waha(payload):
    data = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    message = data.get("message") if isinstance(data.get("message"), dict) else data
    chat_id = data.get("chatId") or message.get("chatId") or _get(data, "from")
    body = (
        message.get("body")
        or message.get("text")
        or _get(message, "text", "body")
        or _get(message, "textMessage", "text")
        or data.get("body")
    )
    ts = data.get("timestamp") or message.get("timestamp")
    parsed_ts = None
    if ts:
        try:
            parsed_ts = datetime.fromtimestamp(int(ts) / (1000 if int(ts) > 9999999999 else 1))
        except Exception:
            parsed_ts = None
    return {
        "session": data.get("session") or payload.get("session"),
        "chat_id": chat_id,
        "sender_id": data.get("sender") or message.get("from") or chat_id,
        "sender_name": data.get("pushName") or message.get("pushName") or data.get("senderName"),
        "body": body,
        "waha_message_id": data.get("id") or message.get("id") or _get(message, "_data", "id", "id"),
        "from_me": bool(data.get("fromMe") or message.get("fromMe")),
        "timestamp": parsed_ts,
        "is_group": bool(data.get("isGroup") or (chat_id and str(chat_id).endswith("@g.us"))),
    }


@webhook_bp.post("/waha")
def waha_webhook():
    payload = request.get_json(silent=True) or {}
    parsed = parse_waha(payload)
    if not parsed["chat_id"]:
        return jsonify({"error": "invalid_payload", "message": "chatId tidak ditemukan"}), 400
    message = Message(**parsed, status="new")
    db.session.add(message)
    db.session.add(MessageLog(direction="in", chat_id=message.chat_id, message=message.body, status="received"))
    db.session.commit()

    relay_client.send_event(get_settings()["relay_flutter_target_device_id"], "inbox_new_message", serialize_message(message))

    if not message.from_me and message.body:
        try:
            handle_auto_reply(message)
        except Exception as exc:
            return jsonify({"ok": True, "message": serialize_message(message), "auto_reply_error": str(exc)}), 202
    return jsonify({"ok": True, "message": serialize_message(message)})
