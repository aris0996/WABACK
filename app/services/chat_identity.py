def _extract_remote_from_message_key(value):
    if not isinstance(value, str):
        return value
    if value.startswith("false_") or value.startswith("true_"):
        parts = value.split("_", 2)
        if len(parts) >= 3 and "@" in parts[1]:
            return parts[1]
    return value


def serialize_chat_id(value):
    if value is None:
        return None
    if isinstance(value, dict):
        raw = value.get("remote") or value.get("_serialized") or value.get("user")
        return _extract_remote_from_message_key(raw)
    return _extract_remote_from_message_key(str(value))


def user_part(value):
    serialized = serialize_chat_id(value)
    if not serialized:
        return None
    return serialized.split("@", 1)[0]


def chat_id_candidates(*values):
    candidates = []
    for value in values:
        serialized = serialize_chat_id(value)
        user = user_part(value)
        suffix_variants = []
        if user and serialized and "@" in serialized and serialized.endswith("@lid"):
            suffix_variants.extend([f"{user}@c.us", f"{user}@s.whatsapp.net"])
        elif user and serialized and "@" in serialized and serialized.endswith("@c.us"):
            suffix_variants.extend([f"{user}@lid", f"{user}@s.whatsapp.net"])
        elif user:
            suffix_variants.extend([f"{user}@c.us", f"{user}@lid", f"{user}@s.whatsapp.net"])
        for candidate in (serialized, user, *suffix_variants):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates
