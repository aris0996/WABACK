import json
import threading
import time

from flask import Blueprint, current_app, jsonify, request

from ..db import execute, get_db, get_setting, query_one
from ..security import normalize_wa_number, parse_wa_number_list, validate_wa_number, webhook_rate_limited
from ..services import chatbot_service, memory_service, waha_service
from ..services.log_service import log_event, log_event_throttled

webhook_bp = Blueprint("webhook", __name__)


def _truth(value):
    return str(value).lower() in ("1", "true", "yes", "on")


def _list_setting(key):
    return parse_wa_number_list(get_setting(key, ""))


def _contact_related_to_allowlist(contact, wa_number, allowlist):
    if wa_number in allowlist or contact["wa_number"] in allowlist:
        return True
    display_name = (contact["display_name"] or "").strip()
    if not display_name or not allowlist:
        return False
    placeholders = ",".join("?" for _ in allowlist)
    row = query_one(
        f"""
        SELECT id
        FROM contacts
        WHERE display_name = ?
          AND wa_number IN ({placeholders})
          AND auto_reply_enabled = 1
          AND ai_blocked = 0
        LIMIT 1
        """,
        (display_name, *allowlist),
    )
    return bool(row)


def _extract_message(payload):
    data = payload.get("payload", payload)
    event = payload.get("event") or payload.get("type") or ""
    if event and event not in ("message", "message.any"):
        return None, None, None
    if _is_true(data.get("fromMe")) or _is_true(data.get("from_me")):
        return None, None, None
    raw_data = data.get("_data") if isinstance(data.get("_data"), dict) else {}
    chat_id = _first_valid_chat_id(
        data.get("from")
        ,
        data.get("chatId"),
        data.get("chat_id"),
        data.get("remoteJid"),
        raw_data.get("from"),
        raw_data.get("remoteJid"),
        _nested_id_value(raw_data.get("id")),
        _nested_id_value(data.get("id")),
    )
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
        body = (
            body.get("text")
            or body.get("body")
            or body.get("conversation")
            or (body.get("extendedTextMessage") or {}).get("text")
            or ""
        )
    if not body and isinstance(raw_data.get("message"), dict):
        raw_message = raw_data["message"]
        body = raw_message.get("conversation") or (raw_message.get("extendedTextMessage") or {}).get("text") or ""
    name = data.get("pushName") or data.get("notifyName") or data.get("senderName") or raw_data.get("notifyName") or ""
    return normalize_wa_number(chat_id), str(body).strip(), name, _normalize_reply_chat_id(chat_id)


def _normalize_reply_chat_id(chat_id):
    text = str(chat_id or "").strip()
    if not text or "@g.us" in text or "@newsletter" in text or text == "status@broadcast":
        return ""
    if "@" in text:
        return text
    normalized = normalize_wa_number(text)
    if validate_wa_number(normalized):
        return f"{normalized}@c.us"
    return ""


def _first_valid_chat_id(*values):
    fallback = ""
    for value in values:
        if not value:
            continue
        text = str(value)
        if not fallback:
            fallback = text
        normalized = normalize_wa_number(text)
        if validate_wa_number(normalized):
            return text
    return fallback


def _nested_id_value(value):
    if isinstance(value, dict):
        return value.get("remote") or value.get("_serialized") or value.get("id") or value.get("user")
    return value


def _is_true(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _webhook_token_valid():
    if not current_app.config["WAHA_WEBHOOK_REQUIRE_TOKEN"]:
        return True
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
    allowlist = _list_setting("allowlist_numbers")
    allowlist_mode = get_setting("allowlist_mode", "false") == "true"
    related_allowed = False
    if allowlist_mode and display_name and allowlist:
        placeholders = ",".join("?" for _ in allowlist)
        related_allowed = bool(
            query_one(
                f"""
                SELECT id
                FROM contacts
                WHERE display_name = ?
                  AND wa_number IN ({placeholders})
                  AND auto_reply_enabled = 1
                  AND ai_blocked = 0
                LIMIT 1
                """,
                (display_name, *allowlist),
            )
        )
    if allowlist_mode and wa_number not in allowlist and not related_allowed:
        default_auto = 0
    else:
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
        return False, "waha_disabled"
    if get_setting("global_auto_reply", "true") != "true":
        return False, "global_auto_reply_off"
    if contact["ai_blocked"]:
        return False, "contact_ai_blocked"
    if wa_number in _list_setting("blocklist_numbers"):
        return False, "number_in_blocklist"
    allowlist_mode = get_setting("allowlist_mode", "false") == "true"
    allowlist = _list_setting("allowlist_numbers")
    related_allowed = _contact_related_to_allowlist(contact, wa_number, allowlist)
    contact_auto_ok = bool(contact["auto_reply_enabled"]) or related_allowed
    if not contact_auto_ok:
        return False, "contact_auto_reply_off"
    if allowlist_mode and not related_allowed and not bool(contact["auto_reply_enabled"]):
        return False, "allowlist_mode_number_not_allowed"
    return True, "allowed"


def _reply_debug_context(contact, wa_number, reason):
    allowlist = _list_setting("allowlist_numbers")
    return {
        "contact_id": contact["id"],
        "wa_number": wa_number,
        "contact_number": contact["wa_number"],
        "display_name": contact["display_name"],
        "reason": reason,
        "waha_enabled": get_setting("waha_enabled", "true"),
        "global_auto_reply": get_setting("global_auto_reply", "true"),
        "contact_auto_reply": bool(contact["auto_reply_enabled"]),
        "contact_ai_blocked": bool(contact["ai_blocked"]),
        "allowlist_mode": get_setting("allowlist_mode", "false"),
        "allowlist_count": len(allowlist),
        "allowlist_exact_match": wa_number in allowlist or contact["wa_number"] in allowlist,
        "allowlist_related_match": _contact_related_to_allowlist(contact, wa_number, allowlist),
    }


def _run_auto_reply(app, contact_id, wa_number, reply_chat_id, message, incoming_message_id):
    with app.app_context():
        started_at = time.monotonic()
        contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        can_reply, reply_reason = _can_reply(contact, wa_number)
        if not can_reply:
            log_event("INFO", "WAHA auto reply skipped", _reply_debug_context(contact, wa_number, reply_reason))
            _run_auto_memory_if_needed(contact_id)
            return
        try:
            delay = float(get_setting("reply_delay_seconds", "0") or 0)
            if delay > 0:
                time.sleep(min(delay, 10))
            ai_started_at = time.monotonic()
            reply = chatbot_service.generate_reply(contact_id, message)
            ai_ms = int((time.monotonic() - ai_started_at) * 1000)
            if not reply:
                log_event("WARNING", "WAHA auto reply empty", {"contact_id": contact_id, "wa_number": wa_number, "ai_ms": ai_ms})
                _run_auto_memory_if_needed(contact_id)
                return
            send_started_at = time.monotonic()
            send_result = waha_service.send_message(wa_number, reply, chat_id=reply_chat_id)
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
                    "wa_number": wa_number,
                    "reply_chat_id": reply_chat_id,
                    "send_result": send_result,
                    "ai_ms": ai_ms,
                    "send_ms": send_ms,
                    "total_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
            _run_auto_memory_if_needed(contact_id)
        except Exception as exc:
            log_event(
                "ERROR",
                "Auto reply failed",
                {"contact_id": contact_id, "error": str(exc), "total_ms": int((time.monotonic() - started_at) * 1000)},
            )


def _run_auto_memory_if_needed(contact_id):
    try:
        if memory_service.should_auto_generate_memory(contact_id):
            log_event("INFO", "Auto memory generation queued after reply", {"contact_id": contact_id})
            memory_service.generate_memory_auto_incremental(contact_id)
    except Exception as exc:
        log_event("ERROR", "Auto memory generation failed", {"contact_id": contact_id, "error": str(exc)})


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
    log_event_throttled(
        "INFO",
        "WAHA webhook received",
        {"event": payload.get("event") or payload.get("type"), "keys": sorted(payload.keys())},
        key="waha-webhook-received",
        window_seconds=60,
    )
    wa_number, message, display_name, reply_chat_id = _extract_message(payload)
    log_event(
        "INFO",
        "WAHA webhook parsed",
        {
            "event": payload.get("event") or payload.get("type"),
            "normalized_number": wa_number,
            "number_valid": validate_wa_number(wa_number),
            "body_len": len(message or ""),
            "display_name": display_name,
            "reply_chat_id": reply_chat_id,
        },
    )
    if not validate_wa_number(wa_number) or not message:
        data = payload.get("payload", payload)
        log_event(
            "INFO",
            "WAHA webhook ignored",
            {
                "event": payload.get("event") or payload.get("type"),
                "keys": sorted(payload.keys()),
                "payload_keys": sorted((payload.get("payload") or {}).keys()) if isinstance(payload.get("payload"), dict) else [],
                "from_raw": str(data.get("from") or "")[:80],
                "to_raw": str(data.get("to") or "")[:80],
                "from_me": data.get("fromMe"),
                "normalized_number": wa_number,
                "number_valid": validate_wa_number(wa_number),
                "body_len": len(message or ""),
                "reason": "not a direct text message",
            },
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
    log_event("INFO", "WAHA inbound message saved", {"contact_id": contact["id"], "wa_number": wa_number, "message_id": cur.lastrowid})

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run_auto_reply,
        args=(app, contact["id"], wa_number, reply_chat_id, message, cur.lastrowid),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "reply_queued": True})
