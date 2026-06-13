from flask import Blueprint, jsonify, request
from ..extensions import db
from ..middleware.auth_required import auth_required
from ..models import Contact

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


@contacts_bp.get("")
@auth_required
def list_contacts():
    contacts = Contact.query.order_by(Contact.updated_at.desc()).all()
    return jsonify([serialize(item) for item in contacts])


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
