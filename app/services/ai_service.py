import re
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
        if not message.from_me:
            contact.last_inbound_at = message.timestamp or datetime.utcnow()
            db.session.commit()
        return contact
    contact = Contact(
        chat_id=message.chat_id,
        name=message.sender_name,
        type="group" if message.is_group else "private",
        permission="blocked",
        reply_mode="disabled",
        last_inbound_at=message.timestamp or datetime.utcnow(),
    )
    db.session.add(contact)
    db.session.commit()
    return contact


def _log_event(message, status, reason=None, *, direction="in", text=None):
    db.session.add(
        MessageLog(
            direction=direction,
            chat_id=message.chat_id,
            message=text if text is not None else (message.body or ""),
            status=status,
            error=reason,
        )
    )
    db.session.commit()


def _log_skip(message, status, reason=None):
    _log_event(message, status, reason)


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


def keyword_matches(contact, text):
    keyword = (contact.trigger_keyword or "").strip()
    if not keyword:
        return False
    haystack = (text or "").strip()
    mode = (contact.keyword_match_mode or "contains").strip().lower()
    if mode == "exact":
        return haystack.lower() == keyword.lower()
    if mode == "regex":
        try:
            return re.search(keyword, haystack, re.IGNORECASE) is not None
        except re.error:
            return False
    return keyword.lower() in haystack.lower()


def daily_limit_reached(contact):
    limit = contact.daily_auto_reply_limit
    if not limit or limit <= 0:
        return False
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = MessageLog.query.filter(
        MessageLog.chat_id == contact.chat_id,
        MessageLog.status == "auto_reply_sent",
        MessageLog.created_at >= start_of_day,
    ).count()
    return count >= limit


def cooldown_active(contact):
    if not contact.cooldown_seconds or contact.cooldown_seconds <= 0 or not contact.last_auto_replied_at:
        return False
    seconds = (datetime.utcnow() - contact.last_auto_replied_at).total_seconds()
    return seconds < contact.cooldown_seconds


def handle_auto_reply(message):
    if message.from_me or not message.body:
        _log_skip(message, "auto_reply_skip", "from_me_or_empty")
        return
    contact = get_contact_for_message(message)
    if contact.permission == "blocked":
        _log_skip(message, "blocked", "contact permission blocked")
        return
    if contact.reply_mode == "disabled":
        _log_skip(message, "disabled", "reply mode disabled")
        return
    if not is_active_now(contact):
        _log_skip(message, "outside_active_hours", f"{contact.active_start or '-'} to {contact.active_end or '-'}")
        return
    if message.is_group:
        if not keyword_matches(contact, message.body):
            _log_skip(message, "keyword_not_matched", f"mode={contact.keyword_match_mode}, keyword={contact.trigger_keyword or '-'}")
            return
    if contact.reply_mode == "manual_only":
        _log_skip(message, "manual_only", "manual review required")
        return
    if contact.reply_mode == "ai_draft":
        generate_ai_draft(message, contact)
        _log_event(message, "draft_created", "draft generated for manual review")
        return
    if contact.reply_mode == "auto_reply" and contact.permission == "allowed":
        if daily_limit_reached(contact):
            _log_skip(message, "daily_limit_reached", f"limit={contact.daily_auto_reply_limit}")
            return
        if cooldown_active(contact):
            _log_skip(message, "cooldown_active", f"cooldown_seconds={contact.cooldown_seconds}")
            return
        try:
            draft = generate_ai_draft(message, contact)
        except Exception as exc:
            if contact.fallback_to_draft_on_error:
                _log_event(message, "fallback_to_draft", f"AI generate failed: {exc}")
                return
            raise
        text = draft.edited_response or draft.response or ""
        try:
            _log_event(message, "auto_reply_start", f"preset=auto priority={contact.priority_level}", direction="out", text=text)
            waha_service.send_typing(message.chat_id)
            waha_service.human_delay(text)
            waha_service.stop_typing(message.chat_id)
            waha_service.send_text(message.chat_id, text)
            message.status = "replied"
            contact.last_auto_replied_at = datetime.utcnow()
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_sent", error=f"cooldown={contact.cooldown_seconds}, limit={contact.daily_auto_reply_limit or 0}"))
            db.session.commit()
            relay_client.send_event(get_settings()["relay_flutter_target_device_id"], "message_replied", {"message_id": message.id, "chat_id": message.chat_id})
        except Exception as exc:
            if contact.fallback_to_draft_on_error:
                message.status = "draft_ready"
                db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="fallback_to_draft", error=str(exc)))
                db.session.commit()
                return
            message.status = "send_error"
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_failed", error=str(exc)))
            db.session.commit()
            raise
