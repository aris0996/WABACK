def serialize_chat_id(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("_serialized") or value.get("remote") or value.get("user")
    return str(value)


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
        for candidate in (serialized, user):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates
