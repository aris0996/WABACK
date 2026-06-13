from flask import Blueprint, jsonify, request
from ..extensions import db
from ..middleware.auth_required import auth_required
from ..models import AiDraft, Contact, Message, MessageLog
from ..services.ai_service import generate_ai_draft, serialize_message
from ..services.relay_client import relay_client
from ..services.settings_service import get_settings
from ..services.waha_service import waha_service

messages_bp = Blueprint("messages", __name__)


def serialize_draft(draft):
    return {
        "id": draft.id,
        "message_id": draft.message_id,
        "prompt": draft.prompt,
        "response": draft.response,
        "edited_response": draft.edited_response,
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def with_drafts(message):
    data = serialize_message(message)
    data["drafts"] = [serialize_draft(draft) for draft in message.drafts]
    return data


@messages_bp.get("")
@auth_required
def list_messages():
    chat_id = request.args.get("chat_id")
    query = Message.query
    if chat_id:
        query = query.filter_by(chat_id=chat_id)
    items = query.order_by(Message.created_at.desc()).limit(int(request.args.get("limit", 100))).all()
    return jsonify([serialize_message(item) for item in items])


@messages_bp.get("/<int:message_id>")
@auth_required
def get_message(message_id):
    return jsonify(with_drafts(Message.query.get_or_404(message_id)))


@messages_bp.get("/chat/<path:chat_id>")
@auth_required
def chat_history(chat_id):
    items = Message.query.filter_by(chat_id=chat_id).order_by(Message.created_at.desc()).limit(50).all()
    return jsonify([serialize_message(item) for item in reversed(items)])


@messages_bp.post("/<int:message_id>/generate-ai")
@auth_required
def generate_ai(message_id):
    draft = generate_ai_draft(Message.query.get_or_404(message_id))
    return jsonify(serialize_draft(draft))


@messages_bp.post("/<int:message_id>/send")
@auth_required
def send_reply(message_id):
    message = Message.query.get_or_404(message_id)
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    draft_id = payload.get("draft_id")
    if draft_id:
        draft = AiDraft.query.get(draft_id)
        if draft and draft.message_id == message.id:
            if text:
                draft.edited_response = text
            text = text or draft.edited_response or draft.response
    if not text:
        return jsonify({"error": "validation_error", "message": "text atau draft_id wajib diisi"}), 400
    try:
        waha_service.send_text(message.chat_id, text)
        message.status = "replied"
        db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="sent"))
        db.session.commit()
        relay_client.send_event(get_settings()["relay_flutter_target_device_id"], "message_replied", {"message_id": message.id, "chat_id": message.chat_id})
        return jsonify({"ok": True, "message": serialize_message(message)})
    except Exception as exc:
        db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="error", error=str(exc)))
        db.session.commit()
        return jsonify({"error": "waha_send_failed", "message": str(exc)}), 502


@messages_bp.post("/<int:message_id>/ignore")
@auth_required
def ignore(message_id):
    message = Message.query.get_or_404(message_id)
    message.status = "ignored"
    db.session.commit()
    return jsonify(serialize_message(message))


@messages_bp.post("/<int:message_id>/block-contact")
@auth_required
def block_contact(message_id):
    message = Message.query.get_or_404(message_id)
    contact = Contact.query.filter_by(chat_id=message.chat_id).first() or Contact(chat_id=message.chat_id, name=message.sender_name)
    contact.permission = "blocked"
    contact.reply_mode = "disabled"
    db.session.add(contact)
    message.status = "contact_blocked"
    db.session.commit()
    return jsonify({"ok": True})
