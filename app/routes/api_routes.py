import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from ..db import execute, get_db, get_settings, query_all, query_one, set_setting
from ..security import chat_key, login_required, normalize_chat_id, require_json, validate_chat_id
from ..services import ollama_service, waha_service
from ..services.log_service import log_event
from ..services.update_service import get_git_status

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _row(row):
    return dict(row) if row else None


def _with_local_time(row):
    item = _row(row)
    if not item or not item.get("created_at"):
        return item
    try:
        dt = datetime.strptime(item["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        item["created_at_local"] = dt.astimezone(ZoneInfo(current_app.config["APP_TIMEZONE"])).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        item["created_at_local"] = item["created_at"]
    return item


def _truth(value):
    return str(value).lower() in ("1", "true", "yes", "on")


@api_bp.get("/config")
@login_required
def get_config():
    return jsonify({"ok": True, "config": get_settings()})


@api_bp.post("/config")
@login_required
def save_config():
    data, error = require_json()
    if error:
        return error
    allowed = set(get_settings().keys())
    for key, value in data.items():
        if key in allowed:
            set_setting(key, value)
    log_event("INFO", "Configuration updated", {"keys": list(data.keys())})
    return jsonify({"ok": True, "config": get_settings()})


@api_bp.get("/contacts")
@login_required
def contacts():
    search = f"%{request.args.get('q', '').strip()}%"
    limit = max(1, min(int(request.args.get("limit", 100)), 300))
    offset = max(0, int(request.args.get("offset", 0)))
    chat_type_filter = request.args.get("type", "").strip()
    auto_filter = request.args.get("auto", "").strip()
    where = ["(wa_number LIKE ? OR COALESCE(display_name, '') LIKE ? OR COALESCE(chat_id, '') LIKE ?)"]
    params = [search, search, search]
    if chat_type_filter in ("direct", "group"):
        where.append("chat_type = ?")
        params.append(chat_type_filter)
    if auto_filter in ("on", "off"):
        where.append("auto_reply_enabled = ?")
        params.append(1 if auto_filter == "on" else 0)
    where_sql = " AND ".join(where)
    total = query_one(
        f"""
        SELECT COUNT(*) AS n
        FROM contacts
        WHERE {where_sql}
        """,
        tuple(params),
    )["n"]
    rows = query_all(
        f"""
        SELECT c.*,
               (
                   SELECT COUNT(*)
                   FROM messages
                   WHERE contact_id = c.id
               ) AS message_count,
               (
                   SELECT MAX(created_at)
                   FROM messages
                   WHERE contact_id = c.id
               ) AS last_chat_at
        FROM contacts c
        WHERE {where_sql}
        ORDER BY COALESCE(last_chat_at, c.created_at) DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [limit, offset]),
    )
    return jsonify({"ok": True, "contacts": [_row(row) for row in rows], "total": total, "limit": limit, "offset": offset})


@api_bp.post("/contacts")
@login_required
def create_contact():
    data, error = require_json()
    if error:
        return error
    chat_id = normalize_chat_id(data.get("wa_number") or data.get("chat_id"))
    key = chat_key(chat_id)
    display_name = str(data.get("display_name", "")).strip()
    if not validate_chat_id(chat_id):
        return jsonify({"ok": False, "error": "Chat ID WhatsApp tidak valid"}), 400
    kind = "group" if chat_id.endswith("@g.us") else "direct"
    try:
        cur = execute(
            """
            INSERT INTO contacts
            (wa_number, chat_id, chat_type, display_name, auto_reply_enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                key,
                chat_id,
                kind,
                display_name,
                0 if kind == "group" else 1 if get_settings().get("default_contact_auto_reply", "true") == "true" else 0,
            ),
        )
        log_event("INFO", "Chat created manually", {"contact_id": cur.lastrowid, "chat_id": chat_id, "chat_type": kind})
        return jsonify({"ok": True, "contact_id": cur.lastrowid})
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            return jsonify({"ok": False, "error": "Nomor sudah ada di kontak"}), 409
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.post("/contacts/sync-waha")
@login_required
def sync_waha_contacts():
    data = request.get_json(silent=True) if request.is_json else {}
    try:
        settings = get_settings()
        limit = max(1, min(int((data or {}).get("limit", settings.get("waha_sync_page_size", "300"))), 1000))
        max_total = max(limit, min(int((data or {}).get("max_total", settings.get("waha_sync_max_contacts", "2000"))), 10000))
        result = waha_service.sync_contacts_from_waha(limit=limit, max_total=max_total)
        log_event("INFO", "Contacts synced from WAHA", result)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        log_event("ERROR", "WAHA contact sync failed", {"error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.get("/contacts/<int:contact_id>")
@login_required
def contact_detail(contact_id):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        return jsonify({"ok": False, "error": "Contact not found"}), 404
    messages = query_all(
        "SELECT * FROM messages WHERE contact_id = ? ORDER BY id DESC LIMIT 150",
        (contact_id,),
    )
    counts = query_one(
        """
        SELECT
            COUNT(*) AS total_messages,
            SUM(CASE WHEN direction = 'in' THEN 1 ELSE 0 END) AS inbound_messages,
            SUM(CASE WHEN direction = 'out' THEN 1 ELSE 0 END) AS outbound_messages
        FROM messages
        WHERE contact_id = ?
        """,
        (contact_id,),
    )
    return jsonify(
        {
            "ok": True,
            "contact": _row(contact),
            "messages": [_row(row) for row in reversed(messages)],
            "counts": _row(counts),
        }
    )


@api_bp.post("/contacts/<int:contact_id>/toggle-auto-reply")
@login_required
def toggle_auto_reply(contact_id):
    contact = query_one("SELECT auto_reply_enabled FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        return jsonify({"ok": False, "error": "Contact not found"}), 404
    execute(
        "UPDATE contacts SET auto_reply_enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (0 if contact["auto_reply_enabled"] else 1, contact_id),
    )
    return jsonify({"ok": True})


@api_bp.post("/contacts/<int:contact_id>/block-ai")
@login_required
def block_ai(contact_id):
    execute("UPDATE contacts SET ai_blocked = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (contact_id,))
    return jsonify({"ok": True})


@api_bp.post("/contacts/<int:contact_id>/unblock-ai")
@login_required
def unblock_ai(contact_id):
    execute("UPDATE contacts SET ai_blocked = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (contact_id,))
    return jsonify({"ok": True})


@api_bp.post("/contacts/<int:contact_id>/memory/generate-all")
@login_required
def generate_all(contact_id):
    return jsonify({"ok": False, "error": "Memory feature removed"}), 410


@api_bp.post("/contacts/<int:contact_id>/memory/generate-new")
@login_required
def generate_new(contact_id):
    return jsonify({"ok": False, "error": "Memory feature removed"}), 410


@api_bp.post("/contacts/<int:contact_id>/memory/reset")
@login_required
def reset_memory(contact_id):
    return jsonify({"ok": False, "error": "Memory feature removed"}), 410


@api_bp.post("/contacts/<int:contact_id>/memory/save")
@login_required
def save_memory(contact_id):
    return jsonify({"ok": False, "error": "Memory feature removed"}), 410


@api_bp.post("/contacts/<int:contact_id>/settings")
@login_required
def save_contact_settings(contact_id):
    data, error = require_json()
    if error:
        return error
    execute(
        """
        UPDATE contacts
        SET display_name = COALESCE(?, display_name),
            trigger_keywords = ?,
            auto_reply_enabled = ?,
            ai_blocked = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            data.get("display_name"),
            str(data.get("trigger_keywords", "")),
            1 if _truth(data.get("auto_reply_enabled")) else 0,
            1 if _truth(data.get("ai_blocked")) else 0,
            contact_id,
        ),
    )
    return jsonify({"ok": True})


@api_bp.get("/contacts/<int:contact_id>/reply-debug")
@login_required
def contact_reply_debug(contact_id):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        return jsonify({"ok": False, "error": "Contact not found"}), 404
    settings = get_settings()
    group_keywords = [item.strip() for item in str(contact["trigger_keywords"] or settings.get("group_trigger_keywords", "")).replace(",", "\n").splitlines() if item.strip()]
    checks = {
        "waha_enabled": settings.get("waha_enabled", "true") == "true",
        "global_auto_reply": settings.get("global_auto_reply", "true") == "true",
        "chat_auto_reply": bool(contact["auto_reply_enabled"]),
        "contact_ai_allowed": not bool(contact["ai_blocked"]),
        "group_trigger_configured": contact["chat_type"] != "group" or bool(group_keywords),
    }
    return jsonify(
        {
            "ok": True,
            "checks": checks,
            "can_reply": all(checks.values()),
            "group_keywords": group_keywords,
            "note": "Direct chat membalas saat auto reply on. Grup hanya membalas jika auto reply on dan pesan mengandung trigger keyword.",
        }
    )


@api_bp.post("/contacts/<int:contact_id>/sync-waha-history")
@login_required
def sync_waha_history(contact_id):
    data = request.get_json(silent=True) if request.is_json else {}
    try:
        limit = max(1, min(int((data or {}).get("limit", get_settings().get("waha_history_sync_limit", "300"))), 1000))
        result = waha_service.sync_contact_messages_from_waha(contact_id, limit=limit)
        log_event("INFO", "WAHA history synced", {"contact_id": contact_id, **result})
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        log_event("ERROR", "WAHA history sync failed", {"contact_id": contact_id, "error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.post("/test-ollama")
@login_required
def test_ollama():
    try:
        return jsonify({"ok": True, "result": ollama_service.test_connection()})
    except Exception as exc:
        log_event("ERROR", "Ollama connection test failed", {"error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.post("/test-waha")
@login_required
def test_waha():
    try:
        return jsonify({"ok": True, "result": waha_service.test_connection()})
    except Exception as exc:
        log_event("ERROR", "WAHA connection test failed", {"error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.post("/send-message")
@login_required
def send_message():
    data, error = require_json()
    if error:
        return error
    contact_id = data.get("contact_id")
    chat_id = normalize_chat_id(data.get("chat_id") or data.get("wa_number"))
    text = str(data.get("message", "")).strip()
    contact = None
    if contact_id:
        contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        if contact:
            chat_id = normalize_chat_id(contact["chat_id"] or contact["wa_number"])
    if not validate_chat_id(chat_id) or not text:
        return jsonify({"ok": False, "error": "Chat ID WhatsApp atau pesan tidak valid"}), 400
    if get_settings().get("waha_enabled", "true") != "true":
        return jsonify({"ok": False, "error": "Integrasi WAHA sedang nonaktif"}), 400
    try:
        result = waha_service.send_message(chat_id, text, chat_id=chat_id)
        if not contact:
            contact = query_one("SELECT id FROM contacts WHERE chat_id = ? OR wa_number = ?", (chat_id, chat_key(chat_id)))
        if contact:
            execute(
                "INSERT INTO messages (contact_id, direction, message, raw_payload) VALUES (?, 'out', ?, ?)",
                (contact["id"], text, json.dumps({"manual": True}, ensure_ascii=False)),
            )
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        log_event("ERROR", "Manual message failed", {"chat_id": chat_id, "error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.get("/logs")
@login_required
def logs():
    limit = max(1, min(int(request.args.get("limit", 100)), 500))
    q = request.args.get("q", "").strip()
    level = request.args.get("level", "").strip().upper()
    params = []
    where = []
    if q:
        where.append("(message LIKE ? OR context_json LIKE ? OR level LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if level:
        where.append("level = ?")
        params.append(level)
    sql = "SELECT * FROM system_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = query_all(sql, tuple(params))
    return jsonify({"ok": True, "logs": [_with_local_time(row) for row in rows]})


@api_bp.get("/ai-logs")
@login_required
def ai_logs():
    limit = max(1, min(int(request.args.get("limit", 150)), 500))
    q = request.args.get("q", "").strip()
    like_terms = [
        "%WAHA webhook%",
        "%WAHA inbound%",
        "%auto reply%",
        "%Auto reply%",
        "%Ollama%",
    ]
    where = ["(" + " OR ".join(["message LIKE ?"] * len(like_terms)) + ")"]
    params = list(like_terms)
    if q:
        where.append("(message LIKE ? OR context_json LIKE ? OR level LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    sql = "SELECT * FROM system_logs WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = query_all(sql, tuple(params))
    return jsonify({"ok": True, "logs": [_with_local_time(row) for row in rows]})


@api_bp.get("/overview")
@login_required
def overview():
    db = get_db()
    stats = {
        "contacts": db.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"],
        "groups": db.execute("SELECT COUNT(*) AS n FROM contacts WHERE chat_type = 'group'").fetchone()["n"],
        "messages": db.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"],
    }
    cfg = get_settings()
    return jsonify({"ok": True, "stats": stats, "config": cfg})


@api_bp.get("/update-status")
@login_required
def update_status():
    try:
        return jsonify({"ok": True, "status": get_git_status()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.get("/memory-jobs/<int:job_id>")
@login_required
def memory_job_status(job_id):
    return jsonify({"ok": False, "error": "Memory feature removed"}), 410
