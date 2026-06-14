from datetime import datetime
from ..extensions import db
from ..models import AiDraft, Contact, Message, MessageLog
from .settings_service import get_settings, setting_bool
from .ollama_service import ollama_service
from .relay_client import relay_client
from .waha_service import waha_service
from .chat_identity import chat_id_candidates


def serialize_message(message):
    return {
        "id": message.id,
        "waha_message_id": message.waha_message_id,
        "session": message.session,
        "chat_id": message.chat_id,
        "sender_id": message.sender_id,
        "sender_name": message.sender_name,
        "body": message.body,
        "from_me": message.from_me,
        "is_group": message.is_group,
        "status": message.status,
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def get_contact_for_message(message):
    candidates = chat_id_candidates(message.chat_id, message.sender_id)
    contact = None
    for candidate in candidates:
        contact = Contact.query.filter_by(chat_id=candidate).first()
        if contact:
            break
    if contact:
        if contact.chat_id != message.chat_id and message.chat_id:
            # Keep the latest concrete chat id so future matching becomes simpler.
            contact.chat_id = message.chat_id
            db.session.commit()
        return contact
    contact = Contact(
        chat_id=message.chat_id,
        name=message.sender_name,
        type="group" if message.is_group else "private",
        permission="blocked",
        reply_mode="disabled",
    )
    db.session.add(contact)
    db.session.commit()
    return contact


def _log_skip(message, reason):
    db.session.add(
        MessageLog(
            direction="in",
            chat_id=message.chat_id,
            message=message.body or "",
            status="skip",
            error=reason,
        )
    )
    db.session.commit()


def build_prompt(message, contact=None):
    settings = get_settings()
    history = (
        Message.query.filter_by(chat_id=message.chat_id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )
    history = list(reversed(history))
    style = contact.ai_style_override if contact and contact.ai_style_override else settings["ai_style"]
    max_chars = contact.max_chars_override if contact and contact.max_chars_override else settings["ollama_max_chars"]
    transcript = "\n".join(
        f"{'Admin' if item.from_me else (item.sender_name or item.sender_id or 'User')}: {item.body}"
        for item in history
        if item.body
    )
    return f"""{settings["system_prompt"]}

Gaya bahasa: {style}
Batas panjang jawaban: maksimal {max_chars} karakter.

Konteks 10 pesan terakhir:
{transcript}

Pesan terbaru:
{message.body}

Instruksi:
- Jangan mengarang data yang tidak diketahui.
- Jika butuh data tambahan, minta klarifikasi singkat.
- Jawab dalam bahasa Indonesia kecuali user memakai bahasa lain.
- Berikan hanya isi balasan WhatsApp, tanpa markdown berlebihan."""


def generate_ai_draft(message, contact=None):
    settings = get_settings()
    contact = contact or get_contact_for_message(message)
    prompt = build_prompt(message, contact)
    draft = AiDraft(message_id=message.id, prompt=prompt, status="generating")
    db.session.add(draft)
    message.status = "drafting"
    db.session.commit()

    target = settings["relay_flutter_target_device_id"]
    stream = setting_bool(settings.get("stream_enabled"), True)
    chunks = []
    try:
        if stream:
            for chunk, done in ollama_service.generate_stream(
                prompt,
                settings["ollama_model"],
                settings["ollama_temperature"],
                settings["ollama_base_url"],
            ):
                if chunk:
                    chunks.append(chunk)
                    relay_client.send_event(target, "ai_stream_chunk", {"message_id": message.id, "draft_id": draft.id, "chunk": chunk})
        else:
            chunks.append(
                ollama_service.generate(
                    prompt,
                    settings["ollama_model"],
                    settings["ollama_temperature"],
                    False,
                    settings["ollama_base_url"],
                )
            )
        draft.response = "".join(chunks).strip()
        draft.status = "ready"
        message.status = "draft_ready"
        db.session.commit()
        relay_client.send_event(target, "ai_draft_ready", {"message_id": message.id, "draft_id": draft.id, "response": draft.response})
        return draft
    except Exception as exc:
        draft.status = "error"
        message.status = "ai_error"
        db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message="", status="ai_error", error=str(exc)))
        db.session.commit()
        raise


def is_active_now(contact):
    if not contact.active_start or not contact.active_end:
        return True
    now = datetime.now().strftime("%H:%M")
    if contact.active_start <= contact.active_end:
        return contact.active_start <= now <= contact.active_end
    return now >= contact.active_start or now <= contact.active_end


def handle_auto_reply(message):
    if message.from_me or not message.body:
        _log_skip(message, "skip: from_me_or_empty")
        return
    contact = get_contact_for_message(message)
    if contact.permission == "blocked" or contact.reply_mode == "disabled":
        _log_skip(message, f"skip: contact_permission={contact.permission}, reply_mode={contact.reply_mode}")
        return
    if not is_active_now(contact):
        _log_skip(message, "skip: outside_active_hours")
        return
    if message.is_group:
        keyword = (contact.trigger_keyword or "").lower().strip()
        if not keyword or keyword not in (message.body or "").lower():
            _log_skip(message, f"skip: group_without_keyword keyword={keyword or '-'}")
            return
    if contact.reply_mode == "manual_only":
        _log_skip(message, "skip: manual_only")
        return
    if contact.reply_mode == "ai_draft":
        generate_ai_draft(message, contact)
        return
    if contact.reply_mode == "auto_reply" and contact.permission == "allowed":
        draft = generate_ai_draft(message, contact)
        text = draft.edited_response or draft.response or ""
        try:
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_start"))
            db.session.commit()
            waha_service.send_typing(message.chat_id)
            waha_service.human_delay(text)
            waha_service.stop_typing(message.chat_id)
            waha_service.send_text(message.chat_id, text)
            message.status = "replied"
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_sent"))
            db.session.commit()
            relay_client.send_event(get_settings()["relay_flutter_target_device_id"], "message_replied", {"message_id": message.id, "chat_id": message.chat_id})
        except Exception as exc:
            message.status = "send_error"
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_failed", error=str(exc)))
            db.session.commit()
            raise
