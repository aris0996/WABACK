import json
import time

from flask import Blueprint, current_app, jsonify, request

from ..db import execute, get_db, get_setting, query_one
from ..security import normalize_wa_number, validate_wa_number, webhook_rate_limited
from ..services import chatbot_service, memory_service, waha_service
from ..services.log_service import log_event, log_event_throttled

webhook_bp = Blueprint("webhook", __name__)


def _truth(value):
    return str(value).lower() in ("1", "true", "yes", "on")


def _list_setting(key):
    return {normalize_wa_number(item.strip()) for item in get_setting(key, "").splitlines() if item.strip()}


def _extract_message(payload):
    data = payload.get("payload", payload)
    event = payload.get("event") or payload.get("type") or ""
    if event and event not in ("message", "message.any"):
        return None, None, None
    if data.get("fromMe") or data.get("from_me"):
        return None, None, None
    raw_data = data.get("_data") if isinstance(data.get("_data"), dict) else {}
    chat_id = (
        data.get("from")
        or data.get("chatId")
        or data.get("chat_id")
        or data.get("remoteJid")
        or raw_data.get("from")
        or raw_data.get("remoteJid")
        or raw_data.get("id", {}).get("remote")
    )
    body = data.get("body") or data.get("text") or data.get("caption") or data.get("message") or raw_data.get("body") or raw_data.get("caption") or ""
    if isinstance(body, dict):
        body = body.get("text") or body.get("body") or ""
    name = data.get("pushName") or data.get("notifyName") or data.get("senderName") or raw_data.get("notifyName") or ""
    return normalize_wa_number(chat_id), str(body).strip(), name


def _webhook_token_valid():
    expected = current_app.config["WEBHOOK_TOKEN"]
    if not expected:
        return True
    provided = (
        request.headers.get("X-Webhook-Token")
        or request.headers.get("X-WAHA-Webhook-Token")
        or request.args.get("token")
        or request.args.get("webhook_token")
        or ""
    )
    auth_header = request.headers.get("Authorization", "")
    if not provided and auth_header.lower().startswith("bearer "):
        provided = auth_header.split(" ", 1)[1].strip()
    return provided == expected


def _get_or_create_contact(wa_number, display_name):
    contact = query_one("SELECT * FROM contacts WHERE wa_number = ?", (wa_number,))
    if contact:
        if display_name and display_name != contact["display_name"]:
            execute(
                "UPDATE contacts SET display_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (display_name, contact["id"]),
            )
        return query_one("SELECT * FROM contacts WHERE id = ?", (contact["id"],))
    default_auto = 1 if _truth(get_setting("default_contact_auto_reply", "true")) else 0
    interval = int(get_setting("memory_generate_interval", "20") or 20)
    cur = execute(
        """
        INSERT INTO contacts
        (wa_number, display_name, auto_reply_enabled, memory_generate_interval)
        VALUES (?, ?, ?, ?)
        """,
        (wa_number, display_name, default_auto, interval),
    )
    return query_one("SELECT * FROM contacts WHERE id = ?", (cur.lastrowid,))


def _can_reply(contact, wa_number):
    if get_setting("waha_enabled", "true") != "true":
        return False
    if get_setting("global_auto_reply", "true") != "true":
        return False
    if contact["ai_blocked"] or not contact["auto_reply_enabled"]:
        return False
    if wa_number in _list_setting("blocklist_numbers"):
        return False
    if get_setting("allowlist_mode", "false") == "true" and wa_number not in _list_setting("allowlist_numbers"):
        return False
    return True


@webhook_bp.post("/webhook/waha")
def waha_webhook():
    if webhook_rate_limited():
        return jsonify({"ok": False, "error": "Rate limit exceeded"}), 429
    if not _webhook_token_valid():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0]
        log_event_throttled(
            "WARNING",
            "Webhook rejected: invalid token",
            {
                "ip": ip,
                "hint": "Set token via X-Webhook-Token, Authorization Bearer, or webhook URL query ?token=WEBHOOK_TOKEN.",
            },
            key=f"bad-webhook-token:{ip}",
            window_seconds=300,
        )
        return jsonify({"ok": True, "ignored": True, "reason": "invalid webhook token"}), 200
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400
    wa_number, message, display_name = _extract_message(payload)
    if not validate_wa_number(wa_number) or not message:
        log_event_throttled(
            "INFO",
            "WAHA webhook ignored",
            {
                "event": payload.get("event") or payload.get("type"),
                "keys": sorted(payload.keys()),
                "payload_keys": sorted((payload.get("payload") or {}).keys()) if isinstance(payload.get("payload"), dict) else [],
                "reason": "not a direct text message",
            },
            key=f"ignored-webhook:{payload.get('event') or payload.get('type')}",
            window_seconds=300,
        )
        return jsonify({"ok": True, "ignored": True})

    contact = _get_or_create_contact(wa_number, display_name)
    db = get_db()
    cur = db.execute(
        "INSERT INTO messages (contact_id, direction, message, raw_payload) VALUES (?, 'in', ?, ?)",
        (contact["id"], message, json.dumps(payload, ensure_ascii=False)),
    )
    db.execute(
        """
        UPDATE contacts
        SET new_message_count_since_memory = new_message_count_since_memory + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (contact["id"],),
    )
    db.commit()

    reply = None
    if _can_reply(contact, wa_number):
        try:
            delay = float(get_setting("reply_delay_seconds", "0") or 0)
            if delay > 0:
                time.sleep(min(delay, 10))
            reply = chatbot_service.generate_reply(contact["id"], message)
            if reply:
                waha_service.send_message(wa_number, reply)
                execute(
                    "INSERT INTO messages (contact_id, direction, message, raw_payload) VALUES (?, 'out', ?, ?)",
                    (contact["id"], reply, json.dumps({"source": "ai", "reply_to": cur.lastrowid}, ensure_ascii=False)),
                )
        except Exception as exc:
            log_event("ERROR", "Auto reply failed", {"contact_id": contact["id"], "error": str(exc)})

    try:
        if memory_service.should_auto_generate_memory(contact["id"]):
            memory_service.generate_memory_auto_incremental(contact["id"])
    except Exception as exc:
        log_event("ERROR", "Auto memory generation failed", {"contact_id": contact["id"], "error": str(exc)})

    return jsonify({"ok": True, "replied": bool(reply)})
