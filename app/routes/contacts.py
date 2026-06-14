from flask import Blueprint, jsonify, request
from ..extensions import db
from ..middleware.auth_required import auth_required
from ..models import Contact, ContactMemory, Message
from ..services.memory_service import get_memories_for_contact, refresh_contact_memory, serialize_memory
from ..services.chat_identity import serialize_chat_id, user_part
from ..services.waha_service import waha_service

contacts_bp = Blueprint("contacts", __name__)


def serialize(contact):
    return {
        "id": contact.id,
        "chat_id": contact.chat_id,
        "name": contact.name,
        "type": contact.type,
        "permission": contact.permission,
        "reply_mode": contact.reply_mode,
        "trigger_keyword": contact.trigger_keyword,
        "active_start": contact.active_start,
        "active_end": contact.active_end,
        "ai_style_override": contact.ai_style_override,
        "max_chars_override": contact.max_chars_override,
        "priority_level": contact.priority_level,
        "daily_auto_reply_limit": contact.daily_auto_reply_limit,
        "cooldown_seconds": contact.cooldown_seconds,
        "fallback_to_draft_on_error": contact.fallback_to_draft_on_error,
        "keyword_match_mode": contact.keyword_match_mode,
        "last_auto_replied_at": contact.last_auto_replied_at.isoformat() if contact.last_auto_replied_at else None,
        "last_inbound_at": contact.last_inbound_at.isoformat() if contact.last_inbound_at else None,
        "preset": detect_preset(contact),
        "notes": contact.notes,
        "memory_summary": contact.memory_summary,
        "memory_count": len(contact.memories or []),
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def parse_int(value):
    if value in (None, "", "null"):
        return None
    return int(value)


def detect_preset(contact):
    if contact.permission == "blocked" or contact.reply_mode == "disabled":
        return "off"
    if contact.reply_mode == "manual_only":
        return "manual"
    if contact.reply_mode == "ai_draft":
        return "draft"
    if contact.reply_mode == "auto_reply" and contact.permission == "allowed":
        return "auto"
    return "custom"


def apply_preset(contact, preset):
    mapping = {
        "off": ("blocked", "disabled"),
        "manual": ("allowed", "manual_only"),
        "draft": ("allowed", "ai_draft"),
        "auto": ("allowed", "auto_reply"),
    }
    if preset not in mapping:
        raise ValueError("preset tidak valid")
    contact.permission, contact.reply_mode = mapping[preset]


def apply(contact, payload):
    if "preset" in payload and payload["preset"]:
        apply_preset(contact, payload["preset"])

    for key in [
        "chat_id",
        "name",
        "type",
        "permission",
        "reply_mode",
        "trigger_keyword",
        "active_start",
        "active_end",
        "ai_style_override",
        "notes",
        "priority_level",
        "keyword_match_mode",
        "memory_summary",
    ]:
        if key in payload:
            setattr(contact, key, payload[key])
    if "max_chars_override" in payload:
        contact.max_chars_override = parse_int(payload["max_chars_override"])
    if "daily_auto_reply_limit" in payload:
        contact.daily_auto_reply_limit = parse_int(payload["daily_auto_reply_limit"])
    if "cooldown_seconds" in payload:
        contact.cooldown_seconds = parse_int(payload["cooldown_seconds"]) or 0
    if "fallback_to_draft_on_error" in payload:
        contact.fallback_to_draft_on_error = parse_bool(payload["fallback_to_draft_on_error"])


def _chat_id_from_waha(chat):
    if not isinstance(chat, dict):
        return None
    raw_id = chat.get("id") or chat.get("chatId")
    return serialize_chat_id(raw_id)


def _name_from_waha(chat, chat_id):
    return (
        chat.get("name")
        or chat.get("pushName")
        or chat.get("formattedTitle")
        or chat.get("contact", {}).get("name")
        or chat.get("contact", {}).get("pushname")
        or chat_id
    )


def serialize_waha_chat(chat):
    chat_id = _chat_id_from_waha(chat)
    last_message = chat.get("lastMessage") or {}
    return {
        "chat_id": chat_id,
        "name": _name_from_waha(chat, chat_id),
        "type": "group" if chat.get("isGroup") or (chat_id and str(chat_id).endswith("@g.us")) else "private",
        "unread_count": chat.get("unreadCount") or chat.get("unread_count") or 0,
        "timestamp": chat.get("timestamp") or last_message.get("timestamp"),
        "last_message": last_message.get("body") or last_message.get("text") or chat.get("lastMessageText") or "",
        "raw": chat,
    }


def _sort_chats_newest_first(chats):
    def key(chat):
        value = chat.get("timestamp") or chat.get("lastMessage", {}).get("timestamp") or 0
        try:
            return int(value)
        except Exception:
            return 0

    return sorted(chats, key=key, reverse=True)


def _local_chats_from_messages(limit=300):
    latest = Message.query.order_by(Message.created_at.desc()).limit(limit).all()
    seen = set()
    chats = []
    for message in latest:
        if message.chat_id in seen:
            continue
        seen.add(message.chat_id)
        chats.append({
            "chat_id": message.chat_id,
            "name": message.sender_name or message.sender_id or message.chat_id,
            "type": "group" if message.is_group else "private",
            "unread_count": 0,
            "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            "last_message": message.body or "",
            "source": "local_messages",
        })
    return chats


def _sync_chat_rows(chats):
    synced = 0
    for chat in chats:
        chat_id = chat.get("chat_id") or _chat_id_from_waha(chat)
        if not chat_id:
            continue
        contact = Contact.query.filter_by(chat_id=chat_id).first()
        if not contact:
            short_id = user_part(chat_id)
            if short_id:
                contact = Contact.query.filter_by(chat_id=short_id).first()
        is_group = bool(chat.get("isGroup") or chat.get("type") == "group" or str(chat_id).endswith("@g.us"))
        if not contact:
            contact = Contact(
                chat_id=chat_id,
                permission="blocked",
                reply_mode="disabled",
            )
            db.session.add(contact)
        elif contact.permission == "default":
            contact.permission = "blocked"
            contact.reply_mode = "disabled"
        contact.name = chat.get("name") or _name_from_waha(chat, chat_id)
        contact.type = "group" if is_group else "private"
        synced += 1
    return synced


@contacts_bp.get("")
@auth_required
def list_contacts():
    contacts = Contact.query.order_by(Contact.updated_at.desc()).all()
    return jsonify([serialize(item) for item in contacts])


@contacts_bp.get("/summary")
@auth_required
def contacts_summary():
    contacts = Contact.query.all()
    return jsonify({
        "total": len(contacts),
        "blocked": sum(1 for item in contacts if item.permission == "blocked"),
        "allowed": sum(1 for item in contacts if item.permission == "allowed"),
        "draft": sum(1 for item in contacts if item.reply_mode == "ai_draft"),
        "auto_reply": sum(1 for item in contacts if item.reply_mode == "auto_reply"),
        "manual_only": sum(1 for item in contacts if item.reply_mode == "manual_only"),
        "groups": sum(1 for item in contacts if item.type == "group"),
        "private": sum(1 for item in contacts if item.type != "group"),
        "vip": sum(1 for item in contacts if item.priority_level == "vip"),
    })


@contacts_bp.get("/waha")
@auth_required
def list_waha_chats():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        chats = waha_service.get_chats(limit=limit, offset=offset)
        rows = [serialize_waha_chat(chat) for chat in _sort_chats_newest_first(chats) if _chat_id_from_waha(chat)]
        return jsonify(rows)
    except Exception as exc:
        if request.args.get("fallback", "true").lower() in ("1", "true", "yes", "on"):
            return jsonify({
                "source": "local_messages",
                "warning": str(exc),
                "items": _local_chats_from_messages(),
            })
        return jsonify({"error": "waha_chats_failed", "message": str(exc)}), 502


@contacts_bp.post("/sync-waha")
@auth_required
def sync_waha_chats():
    try:
        chats = waha_service.get_chats(limit=int(request.args.get("limit", 300)), offset=0)
        synced = _sync_chat_rows(chats)
        db.session.commit()
        return jsonify({"ok": True, "synced": synced, "source": "waha"})
    except Exception as exc:
        db.session.rollback()
        local_chats = _local_chats_from_messages()
        if local_chats:
            synced = _sync_chat_rows(local_chats)
            db.session.commit()
            return jsonify({"ok": True, "synced": synced, "source": "local_messages", "warning": str(exc)})
        return jsonify({"error": "waha_sync_failed", "message": str(exc)}), 502


@contacts_bp.get("/rules-preview/<path:chat_id>")
@auth_required
def rules_preview(chat_id):
    normalized = serialize_chat_id(chat_id)
    contact = Contact.query.filter_by(chat_id=normalized).first()
    if not contact:
        short_id = user_part(normalized)
        if short_id:
            contact = Contact.query.filter_by(chat_id=short_id).first()
    if not contact:
        return jsonify({
            "chat_id": normalized,
            "found": False,
            "effective": {
                "permission": "blocked",
                "reply_mode": "disabled",
                "preset": "off",
            },
        })
    latest_message = Message.query.filter_by(chat_id=contact.chat_id).order_by(Message.created_at.desc()).first()
    return jsonify({
        "chat_id": normalized,
        "found": True,
        "contact": serialize(contact),
        "effective": {
            "permission": contact.permission,
            "reply_mode": contact.reply_mode,
            "preset": detect_preset(contact),
            "type": contact.type,
            "active_window": {"start": contact.active_start, "end": contact.active_end},
            "keyword": contact.trigger_keyword,
            "keyword_match_mode": contact.keyword_match_mode,
            "cooldown_seconds": contact.cooldown_seconds,
            "daily_auto_reply_limit": contact.daily_auto_reply_limit,
            "last_message_body": latest_message.body if latest_message else None,
            "last_message_at": latest_message.created_at.isoformat() if latest_message and latest_message.created_at else None,
        },
    })


@contacts_bp.post("")
@auth_required
def create_contact():
    payload = request.get_json(silent=True) or {}
    if not payload.get("chat_id"):
        return jsonify({"error": "validation_error", "message": "chat_id wajib diisi"}), 400
    contact = Contact(chat_id=payload["chat_id"])
    apply(contact, payload)
    db.session.add(contact)
    db.session.commit()
    return jsonify(serialize(contact)), 201


@contacts_bp.get("/<int:contact_id>")
@auth_required
def get_contact(contact_id):
    return jsonify(serialize(Contact.query.get_or_404(contact_id)))


@contacts_bp.get("/<int:contact_id>/memories")
@auth_required
def list_contact_memories(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    return jsonify({
        "contact": serialize(contact),
        "summary": contact.memory_summary or "",
        "items": [serialize_memory(item) for item in get_memories_for_contact(contact.id)],
    })


@contacts_bp.post("/<int:contact_id>/memories")
@auth_required
def create_contact_memory(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    payload = request.get_json(silent=True) or {}
    content = (payload.get("content") or "").strip()
    if not content:
        return jsonify({"error": "validation_error", "message": "content wajib diisi"}), 400
    item = ContactMemory(
        contact_id=contact.id,
        category=(payload.get("category") or "profile").strip(),
        content=content,
        confidence=(payload.get("confidence") or "medium").strip(),
        pinned=parse_bool(payload.get("pinned")),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(serialize_memory(item)), 201


@contacts_bp.post("/<int:contact_id>/memories/extract")
@auth_required
def extract_contact_memories(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    items = refresh_contact_memory(contact)
    return jsonify({
        "ok": True,
        "summary": contact.memory_summary or "",
        "items": [serialize_memory(item) for item in items],
    })


@contacts_bp.put("/memories/<int:memory_id>")
@auth_required
def update_contact_memory(memory_id):
    item = ContactMemory.query.get_or_404(memory_id)
    payload = request.get_json(silent=True) or {}
    if "category" in payload:
        item.category = (payload.get("category") or "profile").strip()
    if "content" in payload:
        item.content = (payload.get("content") or "").strip()
    if "confidence" in payload:
        item.confidence = (payload.get("confidence") or "medium").strip()
    if "pinned" in payload:
        item.pinned = parse_bool(payload.get("pinned"))
    db.session.commit()
    return jsonify(serialize_memory(item))


@contacts_bp.delete("/memories/<int:memory_id>")
@auth_required
def delete_contact_memory(memory_id):
    item = ContactMemory.query.get_or_404(memory_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True})


@contacts_bp.post("/<int:contact_id>/preset")
@auth_required
def set_contact_preset(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    payload = request.get_json(silent=True) or {}
    preset = (payload.get("preset") or "").strip().lower()
    if not preset:
        return jsonify({"error": "validation_error", "message": "preset wajib diisi"}), 400
    try:
        apply_preset(contact, preset)
    except ValueError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    db.session.commit()
    return jsonify(serialize(contact))


@contacts_bp.put("/<int:contact_id>")
@auth_required
def update_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    apply(contact, request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(serialize(contact))


@contacts_bp.delete("/<int:contact_id>")
@auth_required
def delete_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    db.session.delete(contact)
    db.session.commit()
    return jsonify({"ok": True})
