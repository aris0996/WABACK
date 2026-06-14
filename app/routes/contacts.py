from flask import Blueprint, jsonify, request
from ..extensions import db
from ..middleware.auth_required import auth_required
from ..models import Contact, Message
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
        "notes": contact.notes,
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


def apply(contact, payload):
    for key in ["chat_id", "name", "type", "permission", "reply_mode", "trigger_keyword", "active_start", "active_end", "ai_style_override", "notes"]:
        if key in payload:
            setattr(contact, key, payload[key])
    if "max_chars_override" in payload:
        contact.max_chars_override = payload["max_chars_override"]


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
