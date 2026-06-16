import json

from ..db import execute, get_db, get_setting, query_all, query_one
from ..models import normalize_memory
from . import ollama_service
from .log_service import log_event


def _settings_int(key, default):
    try:
        return int(get_setting(key, str(default)))
    except ValueError:
        return default


def get_new_messages_for_memory(contact_id):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        return []
    return query_all(
        """
        SELECT * FROM messages
        WHERE contact_id = ? AND id > ?
        ORDER BY id ASC
        """,
        (contact_id, contact["last_memory_message_id"]),
    )


def get_all_messages_for_memory(contact_id):
    return query_all(
        "SELECT * FROM messages WHERE contact_id = ? ORDER BY id ASC",
        (contact_id,),
    )


def should_auto_generate_memory(contact_id):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        return False
    if get_setting("memory_auto_generate", "true") != "true":
        return False
    if contact["memory_auto_generate_enabled"] != 1:
        return False
    if get_setting("memory_generate_mode", "manual_auto") == "manual_only":
        return False
    interval = contact["memory_generate_interval"] or _settings_int("memory_generate_interval", 20)
    return contact["new_message_count_since_memory"] >= interval


def _format_messages(messages):
    lines = []
    for row in messages:
        speaker = "User" if row["direction"] == "in" else "Assistant"
        lines.append(f"[{row['id']}] {speaker}: {row['message']}")
    return "\n".join(lines)


def extract_memory_candidate(messages):
    prompt = f"{get_setting('prompt_memory_extractor')}\n\nChat:\n{_format_messages(messages)}"
    model = get_setting("extractor_model", "wa-memory-extractor")
    temp = get_setting("extractor_temperature", "0.1")
    return normalize_memory(ollama_service.generate_json(model, prompt, temp))


def merge_memory(old_memory, new_memory):
    prompt = (
        f"{get_setting('prompt_memory_merger')}\n\n"
        f"Memory lama:\n{json.dumps(normalize_memory(old_memory), ensure_ascii=False)}\n\n"
        f"Memory baru:\n{json.dumps(normalize_memory(new_memory), ensure_ascii=False)}"
    )
    model = get_setting("merger_model", "wa-memory-merger")
    temp = get_setting("merger_temperature", "0.1")
    return normalize_memory(ollama_service.generate_json(model, prompt, temp))


def save_memory(contact_id, memory_json, source="manual_edit"):
    normalized = normalize_memory(memory_json)
    execute(
        """
        INSERT INTO memories (contact_id, memory_json, source, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(contact_id) DO UPDATE SET
            memory_json = excluded.memory_json,
            source = excluded.source,
            updated_at = CURRENT_TIMESTAMP
        """,
        (contact_id, json.dumps(normalized, ensure_ascii=False), source),
    )
    return normalized


def reset_memory(contact_id):
    db = get_db()
    db.execute("DELETE FROM memories WHERE contact_id = ?", (contact_id,))
    db.execute("DELETE FROM memory_candidates WHERE contact_id = ?", (contact_id,))
    db.execute(
        """
        UPDATE contacts
        SET last_memory_message_id = 0,
            new_message_count_since_memory = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (contact_id,),
    )
    db.execute("UPDATE messages SET used_for_memory = 0 WHERE contact_id = ?", (contact_id,))
    db.commit()


def update_memory_checkpoint(contact_id, last_message_id):
    db = get_db()
    db.execute(
        """
        UPDATE contacts
        SET last_memory_message_id = ?,
            new_message_count_since_memory = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (last_message_id, contact_id),
    )
    db.execute(
        "UPDATE messages SET used_for_memory = 1 WHERE contact_id = ? AND id <= ?",
        (contact_id, last_message_id),
    )
    db.commit()


def _generate(contact_id, messages, source_mode, update_checkpoint=True):
    if not messages:
        raise ValueError("Tidak ada pesan untuk generate memory.")
    from_id = messages[0]["id"]
    to_id = messages[-1]["id"]
    candidate = extract_memory_candidate(messages)
    old = query_one("SELECT memory_json FROM memories WHERE contact_id = ?", (contact_id,))
    old_memory = json.loads(old["memory_json"]) if old else {}
    final_memory = merge_memory(old_memory, candidate) if old else candidate
    db = get_db()
    db.execute(
        """
        INSERT INTO memory_candidates
        (contact_id, source_mode, from_message_id, to_message_id, memory_json, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (contact_id, source_mode, from_id, to_id, json.dumps(candidate, ensure_ascii=False), 0.8),
    )
    db.commit()
    save_memory(contact_id, final_memory, source_mode)
    if update_checkpoint:
        update_memory_checkpoint(contact_id, to_id)
    log_event("INFO", "Memory generated", {"contact_id": contact_id, "source": source_mode, "to_id": to_id})
    return final_memory


def generate_memory_all(contact_id):
    return _generate(contact_id, get_all_messages_for_memory(contact_id), "manual_all", True)


def generate_memory_new(contact_id):
    return _generate(contact_id, get_new_messages_for_memory(contact_id), "manual_new", True)


def generate_memory_auto_incremental(contact_id):
    return _generate(contact_id, get_new_messages_for_memory(contact_id), "auto_incremental", True)
