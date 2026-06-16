import json

from flask import Blueprint, jsonify, request

from ..db import execute, get_db, get_settings, query_all, query_one, set_setting
from ..models import normalize_memory
from ..security import login_required, require_json, normalize_wa_number, validate_wa_number
from ..services import memory_service, ollama_service, waha_service
from ..services.log_service import log_event
from ..services.update_service import get_git_status

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _row(row):
    return dict(row) if row else None


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
    rows = query_all(
        """
        SELECT c.*,
               CASE WHEN m.id IS NULL THEN 0 ELSE 1 END AS has_memory,
               MAX(msg.created_at) AS last_chat_at
        FROM contacts c
        LEFT JOIN memories m ON m.contact_id = c.id
        LEFT JOIN messages msg ON msg.contact_id = c.id
        WHERE c.wa_number LIKE ? OR COALESCE(c.display_name, '') LIKE ?
        GROUP BY c.id
        ORDER BY COALESCE(last_chat_at, c.created_at) DESC
        """,
        (search, search),
    )
    return jsonify({"ok": True, "contacts": [_row(row) for row in rows]})


@api_bp.post("/contacts")
@login_required
def create_contact():
    data, error = require_json()
    if error:
        return error
    number = normalize_wa_number(data.get("wa_number"))
    display_name = str(data.get("display_name", "")).strip()
    if not validate_wa_number(number):
        return jsonify({"ok": False, "error": "Nomor WhatsApp tidak valid"}), 400
    try:
        cur = execute(
            """
            INSERT INTO contacts
            (wa_number, display_name, auto_reply_enabled, memory_generate_interval)
            VALUES (?, ?, ?, ?)
            """,
            (
                number,
                display_name,
                1 if get_settings().get("default_contact_auto_reply", "true") == "true" else 0,
                int(get_settings().get("memory_generate_interval", "20") or 20),
            ),
        )
        log_event("INFO", "Contact created manually", {"contact_id": cur.lastrowid, "wa_number": number})
        return jsonify({"ok": True, "contact_id": cur.lastrowid})
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            return jsonify({"ok": False, "error": "Nomor sudah ada di kontak"}), 409
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
    memory = query_one("SELECT * FROM memories WHERE contact_id = ?", (contact_id,))
    return jsonify(
        {
            "ok": True,
            "contact": _row(contact),
            "messages": [_row(row) for row in reversed(messages)],
            "memory": _row(memory),
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
    try:
        return jsonify({"ok": True, "memory": memory_service.generate_memory_all(contact_id)})
    except Exception as exc:
        log_event("ERROR", "Generate all memory failed", {"contact_id": contact_id, "error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.post("/contacts/<int:contact_id>/memory/generate-new")
@login_required
def generate_new(contact_id):
    try:
        return jsonify({"ok": True, "memory": memory_service.generate_memory_new(contact_id)})
    except Exception as exc:
        log_event("ERROR", "Generate new memory failed", {"contact_id": contact_id, "error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.post("/contacts/<int:contact_id>/memory/reset")
@login_required
def reset_memory(contact_id):
    memory_service.reset_memory(contact_id)
    return jsonify({"ok": True})


@api_bp.post("/contacts/<int:contact_id>/memory/save")
@login_required
def save_memory(contact_id):
    data, error = require_json()
    if error:
        return error
    try:
        memory = normalize_memory(data.get("memory_json", {}))
        saved = memory_service.save_memory(contact_id, memory, "manual_edit")
        return jsonify({"ok": True, "memory": saved})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Invalid memory JSON: {exc}"}), 400


@api_bp.post("/contacts/<int:contact_id>/settings")
@login_required
def save_contact_settings(contact_id):
    data, error = require_json()
    if error:
        return error
    interval = max(1, int(data.get("memory_generate_interval", 20)))
    execute(
        """
        UPDATE contacts
        SET memory_auto_generate_enabled = ?,
            memory_generate_interval = ?,
            display_name = COALESCE(?, display_name),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (1 if _truth(data.get("memory_auto_generate_enabled")) else 0, interval, data.get("display_name"), contact_id),
    )
    return jsonify({"ok": True})


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
    number = normalize_wa_number(data.get("wa_number"))
    text = str(data.get("message", "")).strip()
    if not validate_wa_number(number) or not text:
        return jsonify({"ok": False, "error": "Nomor WhatsApp atau pesan tidak valid"}), 400
    if get_settings().get("waha_enabled", "true") != "true":
        return jsonify({"ok": False, "error": "Integrasi WAHA sedang nonaktif"}), 400
    try:
        result = waha_service.send_message(number, text)
        contact = query_one("SELECT id FROM contacts WHERE wa_number = ?", (number,))
        if contact:
            execute(
                "INSERT INTO messages (contact_id, direction, message, raw_payload) VALUES (?, 'out', ?, ?)",
                (contact["id"], text, json.dumps({"manual": True}, ensure_ascii=False)),
            )
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        log_event("ERROR", "Manual message failed", {"wa_number": number, "error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.get("/logs")
@login_required
def logs():
    rows = query_all("SELECT * FROM system_logs ORDER BY id DESC LIMIT 200")
    return jsonify({"ok": True, "logs": [_row(row) for row in rows]})


@api_bp.get("/overview")
@login_required
def overview():
    db = get_db()
    stats = {
        "contacts": db.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"],
        "messages": db.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"],
        "memories": db.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"],
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
