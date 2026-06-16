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
    display_name = contact["display_name"] or contact["wa_number"]
    latest_sender = sender_name or ("Peserta grup" if contact["chat_type"] == "group" else display_name)
    return (
        "Data teknis percakapan WhatsApp:\n"
        f"- Nama chat: {display_name}\n"
        f"- Tipe chat: {contact['chat_type']}\n"
        f"- Pengirim pesan terbaru: {latest_sender}\n\n"
        "Aturan runtime:\n"
        "- Jawab hanya pesan terbaru, dengan mempertimbangkan riwayat terakhir.\n"
        "- Jangan mengulang pertanyaan yang sudah dijawab di riwayat.\n"
        "- Jika lawan bicara memberi nama dirinya, akui secara natural dan lanjutkan percakapan.\n"
        "- Jangan bertanya 'kamu siapa' kecuali identitas lawan benar-benar belum jelas dan memang dibutuhkan.\n"
        "- Jika ditanya siapa pemilik akun, jawab singkat: akun ini milik Faaris.\n"
        "- Jika ditanya siapa kamu, jawab singkat: saya ArisDev AI.\n\n"
        f"Riwayat 5 pesan terbaru:\n{history or '-'}\n\n"
        f"Pesan terbaru:\n{incoming_message}"
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
