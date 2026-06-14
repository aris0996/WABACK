import re
import logging
from datetime import datetime
from ..extensions import db
from ..models import AiDraft, Contact, Message, MessageLog
from .settings_service import get_settings, setting_bool
from .ollama_service import ollama_service
from .relay_client import relay_client
from .waha_service import waha_service
from .chat_identity import chat_id_candidates

logger = logging.getLogger(__name__)


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
    logger.info("Resolving contact for message chat_id=%s sender_id=%s candidates=%s", message.chat_id, message.sender_id, candidates)
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
    logger.info("No contact matched message chat_id=%s, creating default blocked contact", message.chat_id)
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
    logger.info(
        "Generating AI draft for message_id=%s chat_id=%s model=%s stream=%s contact_id=%s",
        message.id,
        message.chat_id,
        settings["ollama_model"],
        setting_bool(settings.get("stream_enabled"), True),
        contact.id if contact else None,
    )
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
        logger.info("AI draft ready for message_id=%s draft_id=%s response_len=%s", message.id, draft.id, len(draft.response or ""))
        relay_client.send_event(target, "ai_draft_ready", {"message_id": message.id, "draft_id": draft.id, "response": draft.response})
        return draft
    except Exception as exc:
        logger.exception("AI draft generation failed for message_id=%s chat_id=%s", message.id, message.chat_id)
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
    logger.info("Auto-reply check: message_id=%s chat_id=%s from_me=%s is_group=%s", message.id, message.chat_id, message.from_me, message.is_group)
    _log_event(
        message,
        "auto_reply_check",
        f"from_me={message.from_me}, is_group={message.is_group}, body_len={len(message.body or '')}",
    )
    if message.from_me or not message.body:
        _log_skip(message, "auto_reply_skip", "from_me_or_empty")
        return
    contact = get_contact_for_message(message)
    logger.info(
        "Auto-reply contact resolved: message_id=%s contact_id=%s permission=%s reply_mode=%s type=%s priority=%s",
        message.id,
        contact.id,
        contact.permission,
        contact.reply_mode,
        contact.type,
        contact.priority_level,
    )
    _log_event(
        message,
        "contact_resolved",
        (
            f"contact_id={contact.id}, permission={contact.permission}, reply_mode={contact.reply_mode}, "
            f"type={contact.type}, priority={contact.priority_level}, chat_id={contact.chat_id}"
        ),
    )
    if contact.permission == "blocked":
        logger.info("Auto-reply blocked by permission for chat_id=%s", message.chat_id)
        _log_skip(message, "blocked", "contact permission blocked")
        return
    if contact.reply_mode == "disabled":
        logger.info("Auto-reply blocked by disabled mode for chat_id=%s", message.chat_id)
        _log_skip(message, "disabled", "reply mode disabled")
        return
    if not is_active_now(contact):
        logger.info("Auto-reply blocked by active hours for chat_id=%s", message.chat_id)
        _log_skip(message, "outside_active_hours", f"{contact.active_start or '-'} to {contact.active_end or '-'}")
        return
    if message.is_group:
        if not keyword_matches(contact, message.body):
            logger.info("Auto-reply blocked by keyword for group chat_id=%s", message.chat_id)
            _log_skip(message, "keyword_not_matched", f"mode={contact.keyword_match_mode}, keyword={contact.trigger_keyword or '-'}")
            return
    if contact.reply_mode == "manual_only":
        logger.info("Auto-reply blocked by manual_only for chat_id=%s", message.chat_id)
        _log_skip(message, "manual_only", "manual review required")
        return
    if contact.reply_mode == "ai_draft":
        logger.info("Generating manual AI draft for chat_id=%s", message.chat_id)
        generate_ai_draft(message, contact)
        _log_event(message, "draft_created", "draft generated for manual review")
        return
    if contact.reply_mode == "auto_reply" and contact.permission == "allowed":
        if daily_limit_reached(contact):
            logger.info("Auto-reply blocked by daily limit for chat_id=%s", message.chat_id)
            _log_skip(message, "daily_limit_reached", f"limit={contact.daily_auto_reply_limit}")
            return
        if cooldown_active(contact):
            logger.info("Auto-reply blocked by cooldown for chat_id=%s", message.chat_id)
            _log_skip(message, "cooldown_active", f"cooldown_seconds={contact.cooldown_seconds}")
            return
        try:
            draft = generate_ai_draft(message, contact)
        except Exception as exc:
            if contact.fallback_to_draft_on_error:
                logger.warning("AI generation failed, fallback to draft for chat_id=%s error=%s", message.chat_id, exc)
                _log_event(message, "fallback_to_draft", f"AI generate failed: {exc}")
                return
            raise
        text = draft.edited_response or draft.response or ""
        if not text.strip():
            logger.warning("AI returned empty response for chat_id=%s", message.chat_id)
            message.status = "draft_ready"
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message="", status="empty_ai_response", error="AI draft kosong"))
            db.session.commit()
            return
        try:
            logger.info("Sending auto-reply to WAHA chat_id=%s text_len=%s", message.chat_id, len(text))
            _log_event(message, "auto_reply_start", f"preset=auto priority={contact.priority_level}", direction="out", text=text)
            waha_service.send_typing(message.chat_id)
            waha_service.human_delay(text)
            waha_service.stop_typing(message.chat_id)
            waha_service.send_text(message.chat_id, text)
            message.status = "replied"
            contact.last_auto_replied_at = datetime.utcnow()
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_sent", error=f"cooldown={contact.cooldown_seconds}, limit={contact.daily_auto_reply_limit or 0}"))
            db.session.commit()
            logger.info("Auto-reply sent successfully for chat_id=%s", message.chat_id)
            relay_client.send_event(get_settings()["relay_flutter_target_device_id"], "message_replied", {"message_id": message.id, "chat_id": message.chat_id})
            return
        except Exception as exc:
            if contact.fallback_to_draft_on_error:
                logger.warning("WAHA send failed, fallback to draft for chat_id=%s error=%s", message.chat_id, exc)
                message.status = "draft_ready"
                db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="fallback_to_draft", error=str(exc)))
                db.session.commit()
                return
            message.status = "send_error"
            db.session.add(MessageLog(direction="out", chat_id=message.chat_id, message=text, status="auto_reply_failed", error=str(exc)))
            db.session.commit()
            logger.exception("Auto-reply send failed for chat_id=%s", message.chat_id)
            raise
    logger.info("Auto-reply not executed for chat_id=%s permission=%s reply_mode=%s", message.chat_id, contact.permission, contact.reply_mode)
    _log_skip(message, "auto_reply_not_executed", f"permission={contact.permission}, reply_mode={contact.reply_mode}")
