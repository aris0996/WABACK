from ..db import get_setting, query_all, query_one
from . import ollama_service


def _settings_int(key, default):
    try:
        return int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return default


def _recent_messages(contact_id):
    limit = max(1, min(_settings_int("history_context_limit", 5), 20))
    rows = query_all(
        """
        SELECT direction, message, sender_name
        FROM messages
        WHERE contact_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (contact_id, limit),
    )
    return list(reversed(rows))


def _format_history(contact, messages):
    lines = []
    for row in messages:
        if row["direction"] == "out":
            speaker = "Saya"
        elif contact["chat_type"] == "group":
            speaker = row["sender_name"] or "Peserta"
        else:
            speaker = "User"
        lines.append(f"{speaker}: {row['message']}")
    return "\n".join(lines)


def build_runtime_prompt(contact, incoming_message, sender_name=""):
    history = _format_history(contact, _recent_messages(contact["id"]))
    prompt = get_setting("prompt_chatbot", "Jawab pesan WhatsApp secara singkat dan natural.")
    display_name = contact["display_name"] or contact["wa_number"]
    latest_sender = sender_name or ("Peserta grup" if contact["chat_type"] == "group" else display_name)
    return (
        f"{prompt}\n\n"
        f"Nama chat/lawan bicara: {display_name}\n"
        f"Tipe chat: {contact['chat_type']}\n"
        f"Pengirim pesan terbaru: {latest_sender}\n\n"
        f"Konteks 5 pesan terbaru:\n{history or '-'}\n\n"
        f"Pesan terbaru yang perlu dijawab:\n{incoming_message}"
    )


def generate_reply(contact_id, incoming_message, sender_name=""):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact or contact["ai_blocked"] or not contact["auto_reply_enabled"]:
        return None
    prompt = build_runtime_prompt(contact, incoming_message, sender_name=sender_name)
    return ollama_service.generate(
        get_setting("chatbot_model", "wa-chatbot"),
        prompt,
        get_setting("chatbot_temperature", "0.3"),
        num_predict=get_setting("chatbot_num_predict", "180"),
    )
