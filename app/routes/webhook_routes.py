import json
import re
import threading
import time

from flask import Blueprint, current_app, jsonify, request

from ..db import execute, get_db, get_setting, query_one
from ..security import chat_key, chat_type, normalize_chat_id, webhook_rate_limited
from ..services import chatbot_service, waha_service
from ..services.log_service import log_event, log_event_throttled

webhook_bp = Blueprint("webhook", __name__)


def _truth(value):
    return str(value).lower() in ("1", "true", "yes", "on")


def _split_keywords(value):
    return [item.lower() for item in re.split(r"[\s,;]+", str(value or "")) if item.strip()]


def _keywords_for_chat(contact):
    return _split_keywords(contact["trigger_keywords"] or get_setting("group_trigger_keywords", ""))


def _has_group_trigger(contact, message):
    if contact["chat_type"] != "group":
        return True
    text = str(message or "").lower()
    return any(keyword in text for keyword in _keywords_for_chat(contact))


def _is_true(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")


def _nested_id_value(value):
    if isinstance(value, dict):
        return value.get("remote") or value.get("_serialized") or value.get("id") or value.get("user")
    return value


def _first_chat_id(*values):
    fallback = ""
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not fallback:
            fallback = text
        chat_id = normalize_chat_id(text)
        if chat_id:
            return chat_id
    return normalize_chat_id(fallback)


def _message_body(data, raw_data):
    body = (
        data.get("body")
        or data.get("text")
        or data.get("caption")
        or data.get("message")
        or data.get("messageBody")
        or raw_data.get("body")
        or raw_data.get("caption")
        or raw_data.get("text")
        or ""
    )
    if isinstance(body, dict):
        body = body.get("text") or body.get("body") or body.get("conversation") or (body.get("extendedTextMessage") or {}).get("text") or ""
    if not body and isinstance(raw_data.get("message"), dict):
        raw_message = raw_data["message"]
        body = raw_message.get("conversation") or (raw_message.get("extendedTextMessage") or {}).get("text") or ""
    return str(body or "").strip()


def _extract_message(payload):
    data = payload.get("payload", payload)
    event = payload.get("event") or payload.get("type") or ""
    if event and event not in ("message", "message.any"):
        return {"ignored": True, "reason": "unsupported_event"}
    if _is_true(data.get("fromMe")) or _is_true(data.get("from_me")):
        return {"ignored": True, "reason": "from_me"}

    raw_data = data.get("_data") if isinstance(data.get("_data"), dict) else {}
    chat_id = _first_chat_id(
        data.get("from"),
        data.get("chatId"),
        data.get("chat_id"),
        data.get("remoteJid"),
        raw_data.get("from"),
        raw_data.get("remoteJid"),
        _nested_id_value(raw_data.get("id")),
        _nested_id_value(data.get("id")),
    )
    if not chat_id:
        return {"ignored": True, "reason": "unsupported_chat_id"}

    body = _message_body(data, raw_data)
    if not body:
        return {"ignored": True, "reason": "empty_text"}

    return {
        "ignored": False,
        "chat_id": chat_id,
        "chat_key": chat_key(chat_id),
        "chat_type": chat_type(chat_id),
        "message": body,
        "display_name": data.get("pushName") or data.get("notifyName") or data.get("senderName") or raw_data.get("notifyName") or "",
        "sender_id": str(data.get("participant") or data.get("author") or raw_data.get("participant") or raw_data.get("author") or ""),
        "sender_name": str(data.get("pushName") or data.get("notifyName") or data.get("senderName") or raw_data.get("notifyName") or ""),
        "external_id": str((_nested_id_value(data.get("id")) or _nested_id_value(raw_data.get("id")) or payload.get("id") or "")),
    }


def _webhook_token_valid():
    if not current_app.config["WAHA_WEBHOOK_REQUIRE_TOKEN"]:
        return True
    expected = current_app.config["WEBHOOK_TOKEN"]
    if not expected:
        return True
    provided = request.headers.get("X-Webhook-Token") or request.headers.get("X-WAHA-Webhook-Token") or request.args.get("token") or ""
    auth_header = request.headers.get("Authorization", "")
    if not provided and auth_header.lower().startswith("bearer "):
        provided = auth_header.split(" ", 1)[1].strip()
    return provided == expected


def _get_or_create_chat(parsed):
    contact = query_one("SELECT * FROM contacts WHERE chat_id = ? OR wa_number = ?", (parsed["chat_id"], parsed["chat_key"]))
    if contact:
        execute(
            """
            UPDATE contacts
            SET chat_id = ?, chat_type = ?, display_name = COALESCE(NULLIF(?, ''), display_name), updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (parsed["chat_id"], parsed["chat_type"], parsed["display_name"], contact["id"]),
        )
        return query_one("SELECT * FROM contacts WHERE id = ?", (contact["id"],))

    default_auto = 0 if parsed["chat_type"] == "group" else 1 if _truth(get_setting("default_contact_auto_reply", "true")) else 0
    cur = execute(
        """
        INSERT INTO contacts (wa_number, chat_id, chat_type, display_name, auto_reply_enabled)
        VALUES (?, ?, ?, ?, ?)
        """,
        (parsed["chat_key"], parsed["chat_id"], parsed["chat_type"], parsed["display_name"], default_auto),
    )
    return query_one("SELECT * FROM contacts WHERE id = ?", (cur.lastrowid,))


def _can_reply(contact, message):
    if get_setting("waha_enabled", "true") != "true":
        return False, "waha_disabled"
    if get_setting("global_auto_reply", "true") != "true":
        return False, "global_auto_reply_off"
    if contact["ai_blocked"]:
        return False, "contact_ai_blocked"
    if not contact["auto_reply_enabled"]:
        return False, "chat_auto_reply_off"
    if contact["chat_type"] == "group" and not _has_group_trigger(contact, message):
        return False, "group_trigger_not_matched"
    return True, "allowed"


def _run_auto_reply(app, contact_id, message, incoming_message_id):
    with app.app_context():
        started_at = time.monotonic()
        contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        can_reply, reason = _can_reply(contact, message)
        if not can_reply:
            log_event("INFO", "WAHA auto reply skipped", {"contact_id": contact_id, "chat_id": contact["chat_id"], "reason": reason})
            return
        try:
            delay = float(get_setting("reply_delay_seconds", "0") or 0)
            if delay > 0:
                time.sleep(min(delay, 10))
            ai_started_at = time.monotonic()
            reply = chatbot_service.generate_reply(contact_id, message)
            ai_ms = int((time.monotonic() - ai_started_at) * 1000)
            if not reply:
                log_event("WARNING", "WAHA auto reply empty", {"contact_id": contact_id, "chat_id": contact["chat_id"], "ai_ms": ai_ms})
                return
            send_started_at = time.monotonic()
            send_result = waha_service.send_message(contact["wa_number"], reply, chat_id=contact["chat_id"])
            send_ms = int((time.monotonic() - send_started_at) * 1000)
            execute(
                "INSERT INTO messages (contact_id, direction, message, raw_payload) VALUES (?, 'out', ?, ?)",
                (contact_id, reply, json.dumps({"source": "ai", "reply_to": incoming_message_id}, ensure_ascii=False)),
            )
            log_event(
                "INFO",
                "WAHA auto reply sent",
                {
                    "contact_id": contact_id,
                    "chat_id": contact["chat_id"],
                    "chat_type": contact["chat_type"],
                    "send_result": send_result,
                    "ai_ms": ai_ms,
                    "send_ms": send_ms,
                    "total_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
        except Exception as exc:
            log_event("ERROR", "WAHA auto reply failed", {"contact_id": contact_id, "error": str(exc), "total_ms": int((time.monotonic() - started_at) * 1000)})


@webhook_bp.post("/webhook/waha")
def waha_webhook():
    if webhook_rate_limited():
        return jsonify({"ok": False, "error": "Rate limit exceeded"}), 429
    if not _webhook_token_valid():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0]
        log_event_throttled("WARNING", "WAHA webhook rejected: invalid token", {"ip": ip}, key=f"bad-waha-token:{ip}", window_seconds=300)
        return jsonify({"ok": True, "ignored": True, "reason": "invalid webhook token"}), 200

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400

    event = payload.get("event") or payload.get("type")
    log_event_throttled("INFO", "WAHA webhook received", {"event": event, "keys": sorted(payload.keys())}, key="waha-webhook-received", window_seconds=60)
    parsed = _extract_message(payload)
    log_event("INFO", "WAHA webhook parsed", {key: parsed.get(key) for key in ("ignored", "reason", "chat_id", "chat_type", "display_name", "sender_name")})

    if parsed.get("ignored"):
        log_event("INFO", "WAHA webhook ignored", {"event": event, "reason": parsed.get("reason")})
        return jsonify({"ok": True, "ignored": True, "reason": parsed.get("reason")})

    contact = _get_or_create_chat(parsed)
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO messages (contact_id, direction, message, raw_payload, external_id, sender_id, sender_name)
        VALUES (?, 'in', ?, ?, ?, ?, ?)
        """,
        (
            contact["id"],
            parsed["message"],
            json.dumps(payload, ensure_ascii=False),
            parsed["external_id"] or None,
            parsed["sender_id"],
            parsed["sender_name"],
        ),
    )
    db.execute("UPDATE contacts SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (contact["id"],))
    db.commit()
    log_event("INFO", "WAHA inbound message saved", {"contact_id": contact["id"], "chat_id": contact["chat_id"], "chat_type": contact["chat_type"], "message_id": cur.lastrowid})

    app = current_app._get_current_object()
    thread = threading.Thread(target=_run_auto_reply, args=(app, contact["id"], parsed["message"], cur.lastrowid), daemon=True)
    thread.start()
    return jsonify({"ok": True, "reply_queued": True})
