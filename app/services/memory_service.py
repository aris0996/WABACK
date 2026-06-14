import json
import logging
from collections import OrderedDict
from ..extensions import db
from ..models import ContactMemory, Message
from .chat_identity import chat_id_candidates
from .ollama_service import ollama_service
from .settings_service import get_settings

logger = logging.getLogger(__name__)


def serialize_memory(item):
    return {
        "id": item.id,
        "contact_id": item.contact_id,
        "category": item.category,
        "content": item.content,
        "confidence": item.confidence,
        "source_message_id": item.source_message_id,
        "pinned": item.pinned,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def get_memories_for_contact(contact_id):
    return ContactMemory.query.filter_by(contact_id=contact_id).order_by(ContactMemory.pinned.desc(), ContactMemory.updated_at.desc()).all()


def build_memory_block(contact):
    parts = []
    if contact.memory_summary:
        parts.append(f"Ringkasan kontak:\n{contact.memory_summary.strip()}")

    memories = get_memories_for_contact(contact.id)
    if memories:
        lines = [f"- [{item.category}] {item.content}" for item in memories[:8]]
        parts.append("Fakta & preferensi penting:\n" + "\n".join(lines))

    if contact.notes:
        parts.append(f"Catatan admin:\n{contact.notes.strip()}")

    return "\n\n".join(part for part in parts if part.strip())


def _history_lines(contact, limit=24):
    candidate_ids = chat_id_candidates(contact.chat_id)
    rows = (
        Message.query.filter(Message.chat_id.in_(candidate_ids))
        .order_by(Message.created_at.desc())
        .limit(limit * 2)
        .all()
    )
    unique = []
    seen = set()
    for item in rows:
        key = item.waha_message_id or f"{item.chat_id}:{item.timestamp}:{item.body}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    unique.reverse()
    return [
        f"{'Admin' if item.from_me else (item.sender_name or item.sender_id or 'User')}: {(item.body or '').strip()}"
        for item in unique
        if (item.body or "").strip()
    ]


def _fallback_extract(contact):
    text = "\n".join(_history_lines(contact, limit=30))
    lowered = text.lower()
    suggestions = OrderedDict()

    suggestions["profile"] = (
        "Kontak ini adalah chat grup, utamakan konteks dan hindari balasan impulsif."
        if contact.type == "group"
        else "Kontak ini adalah chat pribadi, utamakan nada personal, natural, dan relevan."
    )
    if contact.type == "private":
        suggestions["tone"] = "Gunakan balasan hangat, sederhana, dan tidak terasa seperti bot."
    if contact.priority_level == "vip":
        suggestions["preference"] = "Kontak ini prioritas VIP, utamakan respons hangat, cepat, dan penuh perhatian."
    if contact.ai_style_override:
        suggestions["style_override"] = f"Ikuti gaya khusus kontak ini: {contact.ai_style_override.strip()[:220]}"
    if contact.notes:
        suggestions["notes"] = f"Perhatikan catatan admin ini: {contact.notes.strip()[:220]}"
    if "sayang" in lowered or "ayang" in lowered:
        suggestions["relationship"] = "Kontak ini kemungkinan dekat secara personal; balasan sebaiknya hangat, lembut, dan akrab."
    if "terima kasih" in lowered or "makasih" in lowered:
        suggestions["tone"] = "Kontak ini cocok dijawab dengan nada sopan, hangat, dan tidak kaku."
    if "?" in text:
        suggestions["behavior"] = "Jika pesan tidak jelas, lebih baik klarifikasi singkat daripada mengarang jawaban."

    return [
        {"category": key, "content": value, "confidence": "medium"}
        for key, value in suggestions.items()
    ]


def extract_memories(contact):
    settings = get_settings()
    lines = _history_lines(contact, limit=30)
    if not lines:
        return []

    prompt = f"""Kamu mengekstrak memory kontak untuk AI WhatsApp.

Tugas:
- Ambil hanya informasi stabil dan berguna untuk balasan berikutnya.
- Fokus pada: relasi, gaya bahasa yang disukai, preferensi sapaan, emosi dominan, topik sensitif, dan hal yang sebaiknya dihindari.
- Jangan mengarang fakta.
- Jangan menyimpan detail sesaat yang tidak stabil.
- Jawab HANYA dalam JSON array.

Format JSON:
[
  {{"category":"profile|preference|warning|relationship|tone","content":"...","confidence":"low|medium|high"}}
]

Riwayat chat:
{chr(10).join(lines)}
"""
    try:
        raw = ollama_service.generate(
            prompt,
            settings["ollama_model"],
            settings["ollama_temperature"],
            False,
            settings["ollama_base_url"],
        )
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1 or end < start:
            raise ValueError("Ollama tidak mengembalikan JSON array memory")
        parsed = json.loads(raw[start:end + 1])
        cleaned = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            content = (item.get("content") or "").strip()
            if not content:
                continue
            cleaned.append({
                "category": (item.get("category") or "profile").strip()[:30],
                "content": content[:500],
                "confidence": (item.get("confidence") or "medium").strip()[:20],
            })
        if cleaned:
            return cleaned[:8]
    except Exception as exc:
        logger.warning("Memory extraction fallback for contact_id=%s error=%s", contact.id, exc)
    return _fallback_extract(contact)


def refresh_contact_memory(contact):
    extracted = extract_memories(contact)
    if not extracted:
        extracted = _fallback_extract(contact)

    ContactMemory.query.filter_by(contact_id=contact.id, pinned=False).delete()
    for item in extracted:
        db.session.add(
            ContactMemory(
                contact_id=contact.id,
                category=item["category"],
                content=item["content"],
                confidence=item["confidence"],
                pinned=False,
            )
        )

    grouped = [f"- [{item['category']}] {item['content']}" for item in extracted]
    contact.memory_summary = "\n".join(grouped)
    db.session.commit()
    return get_memories_for_contact(contact.id)
