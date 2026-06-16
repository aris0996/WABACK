import json

from ..db import get_setting, query_one
from . import ollama_service


def build_runtime_prompt_without_memory(incoming_message):
    return f"{get_setting('prompt_chatbot_without_memory')}\n\nPesan user:\n{incoming_message}"


def build_runtime_prompt_with_memory(incoming_message, memory_json):
    return (
        f"{get_setting('prompt_chatbot_with_memory')}\n\n"
        f"Memory internal JSON:\n{json.dumps(memory_json, ensure_ascii=False)}\n\n"
        f"Pesan user:\n{incoming_message}"
    )


def generate_reply(contact_id, incoming_message):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact or contact["ai_blocked"] or not contact["auto_reply_enabled"]:
        return None
    memory = query_one("SELECT memory_json FROM memories WHERE contact_id = ?", (contact_id,))
    if memory:
        prompt = build_runtime_prompt_with_memory(incoming_message, json.loads(memory["memory_json"]))
    else:
        prompt = build_runtime_prompt_without_memory(incoming_message)
    return ollama_service.generate(
        get_setting("chatbot_model", "wa-chatbot"),
        prompt,
        get_setting("chatbot_temperature", "0.3"),
    )
