import json

import requests
from datetime import datetime, timezone
from urllib.parse import quote

from ..db import execute, get_db, get_setting, query_one
from ..security import chat_key, chat_type, normalize_chat_id, validate_chat_id
from .network_service import tcp_probe


def _headers():
    api_key = get_setting("waha_api_key")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _base_url():
    return get_setting("waha_base_url").rstrip("/")


def send_message(wa_number, text, chat_id=None):
    session = get_setting("waha_session", "default")
    target_chat_id = normalize_chat_id(chat_id or wa_number)
    if not target_chat_id:
        raise ValueError("Chat ID WhatsApp tidak valid")
    payload = {"session": session, "chatId": target_chat_id, "text": text}
    response = requests.post(
        f"{_base_url()}/api/sendText",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json() if response.content else {"ok": True}


def test_connection():
    probe = tcp_probe(_base_url())
    if not probe["ok"]:
        raise RuntimeError({"probe": probe, "base_url": _base_url()})
    errors = []
    for path in ("/api/sessions", "/api/server/status"):
        url = f"{_base_url()}{path}"
        try:
            response = requests.get(url, headers=_headers(), timeout=10)
            response.raise_for_status()
            body = response.json() if response.content else {"ok": True}
            return {"url": url, "result": body}
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})
    raise RuntimeError(errors)


def _extract_chat_id(chat):
    for value in _candidate_chat_ids(chat):
        found_chat_id = _normalize_chat_id_value(value)
        if validate_chat_id(found_chat_id):
            return found_chat_id
    return ""


def _candidate_chat_ids(value):
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        server = str(value.get("server") or "")
        user = str(value.get("user") or "")
        if user and server:
            yield f"{user}@{server}"
        for key in (
            "_serialized",
            "serialized",
            "chatId",
            "chat_id",
            "remoteJid",
            "jid",
            "id",
            "wid",
            "number",
            "phone",
            "from",
            "to",
            "participant",
            "conversationId",
        ):
            if key in value:
                yield value[key]
        for key in ("_chat", "chat", "contact", "sender", "recipient", "lastMessage"):
            nested = value.get(key)
            if isinstance(nested, (dict, str)):
                yield from _candidate_chat_ids(nested)
        return
    if isinstance(value, list):
        for item in value:
            yield from _candidate_chat_ids(item)


def _normalize_chat_id_value(value):
    if isinstance(value, dict):
        for candidate in _candidate_chat_ids(value):
            normalized = _normalize_chat_id_value(candidate)
            if validate_chat_id(normalized):
                return normalized
        return ""
    text = str(value or "").strip()
    if not text or text == "status@broadcast" or "@newsletter" in text:
        return ""
    return normalize_chat_id(text)


def _extract_chat_name(chat):
    for key in ("name", "pushName", "displayName", "formattedTitle", "title"):
        value = chat.get(key)
        if value:
            return str(value)
    contact = chat.get("contact") or {}
    if isinstance(contact, dict):
        return str(contact.get("name") or contact.get("pushName") or contact.get("shortName") or "")
    return ""


def fetch_chats(limit=200, offset=0):
    session = get_setting("waha_session", "default")
    base = _base_url()
    candidates = [
        f"{base}/api/{session}/chats/overview?limit={limit}&offset={offset}",
        f"{base}/api/{session}/chats?limit={limit}&offset={offset}&sortBy=messageTimestamp&sortOrder=desc",
    ]
    errors = []
    for url in candidates:
        try:
            response = requests.get(url, headers=_headers(), timeout=30)
            response.raise_for_status()
            data = response.json() if response.content else []
            if isinstance(data, dict):
                data = data.get("chats") or data.get("data") or data.get("items") or []
            return {"url": url, "items": data if isinstance(data, list) else []}
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})
    raise RuntimeError(errors)


def _sync_contact_items(items):
    inserted = 0
    updated = 0
    skipped = 0
    skipped_reasons = {"invalid_chat": 0, "non_object": 0}
    sample_keys = []
    db = get_db()
    for chat in items:
        if not isinstance(chat, dict):
            skipped += 1
            skipped_reasons["non_object"] += 1
            continue
        if len(sample_keys) < 5:
            sample_keys.append(sorted(chat.keys()))
        found_chat_id = _extract_chat_id(chat)
        if not validate_chat_id(found_chat_id):
            skipped += 1
            skipped_reasons["invalid_chat"] += 1
            continue
        key = chat_key(found_chat_id)
        kind = chat_type(found_chat_id)
        name = _extract_chat_name(chat)
        existing = query_one("SELECT id, display_name FROM contacts WHERE chat_id = ? OR wa_number = ?", (found_chat_id, key))
        if existing:
            if name and name != existing["display_name"]:
                db.execute(
                    "UPDATE contacts SET display_name = ?, chat_id = ?, chat_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, found_chat_id, kind, existing["id"]),
                )
                updated += 1
            else:
                db.execute(
                    "UPDATE contacts SET chat_id = ?, chat_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (found_chat_id, kind, existing["id"]),
                )
                skipped += 1
        else:
            db.execute(
                """
                INSERT INTO contacts
                (wa_number, chat_id, chat_type, display_name, auto_reply_enabled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    key,
                    found_chat_id,
                    kind,
                    name,
                    0 if kind == "group" else 1 if get_setting("default_contact_auto_reply", "true") == "true" else 0,
                ),
            )
            inserted += 1
    db.commit()
    return {
        "received": len(items),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "skipped_reasons": skipped_reasons,
        "sample_keys": sample_keys,
    }


def sync_contacts_from_waha(limit=200, max_total=2000):
    offset = 0
    pages = 0
    source_urls = []
    totals = {
        "received": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_reasons": {"invalid_chat": 0, "non_object": 0},
        "sample_keys": [],
    }
    while offset < max_total:
        fetched = fetch_chats(limit=limit, offset=offset)
        items = fetched["items"]
        pages += 1
        source_urls.append(fetched["url"])
        result = _sync_contact_items(items)
        totals["received"] += result["received"]
        totals["inserted"] += result["inserted"]
        totals["updated"] += result["updated"]
        totals["skipped"] += result["skipped"]
        totals["skipped_reasons"]["invalid_chat"] += result["skipped_reasons"]["invalid_chat"]
        totals["skipped_reasons"]["non_object"] += result["skipped_reasons"]["non_object"]
        for keys in result["sample_keys"]:
            if len(totals["sample_keys"]) < 5:
                totals["sample_keys"].append(keys)
        if len(items) < limit:
            break
        offset += limit
    return {
        "source_url": source_urls[0] if source_urls else "",
        "pages": pages,
        "page_size": limit,
        "max_total": max_total,
        **totals,
    }


def _message_text(item):
    if not isinstance(item, dict):
        return ""
    for key in ("body", "text", "caption", "message"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("text") or value.get("body")
            if nested:
                return str(nested).strip()
    data = item.get("_data") or {}
    if isinstance(data, dict):
        for key in ("body", "caption", "text"):
            if data.get(key):
                return str(data[key]).strip()
    return ""


def _message_external_id(item):
    value = item.get("id") if isinstance(item, dict) else ""
    if isinstance(value, dict):
        return str(value.get("_serialized") or value.get("id") or value.get("remote") or "")
    return str(value or "")


def _message_sender_id(item):
    if not isinstance(item, dict):
        return ""
    raw_data = item.get("_data") if isinstance(item.get("_data"), dict) else {}
    return str(
        item.get("participant")
        or item.get("author")
        or item.get("from")
        or raw_data.get("participant")
        or raw_data.get("author")
        or ""
    )


def _message_sender_name(item):
    if not isinstance(item, dict):
        return ""
    raw_data = item.get("_data") if isinstance(item.get("_data"), dict) else {}
    return str(
        item.get("pushName")
        or item.get("notifyName")
        or item.get("senderName")
        or raw_data.get("notifyName")
        or raw_data.get("pushName")
        or ""
    )


def _message_created_at(item):
    ts = item.get("timestamp") if isinstance(item, dict) else None
    try:
        ts = int(ts)
        if ts > 0:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return None


def _is_true(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _message_direction(item):
    if not isinstance(item, dict):
        return "in"
    raw_data = item.get("_data") if isinstance(item.get("_data"), dict) else {}
    for key in ("fromMe", "from_me", "from_me"):
        if key in item and _is_true(item.get(key)):
            return "out"
        if key in raw_data and _is_true(raw_data.get(key)):
            return "out"
    msg_id = item.get("id") or raw_data.get("id") or ""
    if isinstance(msg_id, dict):
        if _is_true(msg_id.get("fromMe")):
            return "out"
        msg_id = msg_id.get("_serialized") or msg_id.get("id") or ""
    msg_id = str(msg_id)
    if msg_id.startswith("true_") or msg_id.startswith("true-"):
        return "out"
    if msg_id.startswith("false_") or msg_id.startswith("false-"):
        return "in"
    return "in"


def fetch_chat_messages(chat_id, limit=300, offset=0):
    session = get_setting("waha_session", "default")
    encoded_chat_id = quote(normalize_chat_id(chat_id), safe="")
    url = (
        f"{_base_url()}/api/{session}/chats/{encoded_chat_id}/messages"
        f"?limit={limit}&offset={offset}&downloadMedia=false"
    )
    response = requests.get(url, headers=_headers(), timeout=60)
    response.raise_for_status()
    data = response.json() if response.content else []
    if isinstance(data, dict):
        data = data.get("messages") or data.get("data") or data.get("items") or []
    return {"url": url, "items": data if isinstance(data, list) else []}


def sync_contact_messages_from_waha(contact_id, limit=300):
    contact = query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        raise ValueError("Contact not found")
    fetched = fetch_chat_messages(contact["chat_id"] or contact["wa_number"], limit=limit)
    inserted = 0
    skipped = 0
    inbound = 0
    outbound = 0
    db = get_db()
    for item in fetched["items"]:
        if not isinstance(item, dict):
            skipped += 1
            continue
        text = _message_text(item)
        external_id = _message_external_id(item)
        if not text:
            skipped += 1
            continue
        direction = _message_direction(item)
        if direction == "out":
            outbound += 1
        else:
            inbound += 1
        created_at = _message_created_at(item)
        params = [
            contact_id,
            direction,
            text,
            json.dumps(item, ensure_ascii=False),
            external_id or None,
            _message_sender_id(item),
            _message_sender_name(item),
        ]
        sql = """
            INSERT OR IGNORE INTO messages
            (contact_id, direction, message, raw_payload, external_id, sender_id, sender_name{created_col})
            VALUES (?, ?, ?, ?, ?, ?, ?{created_param})
        """
        if created_at:
            params.append(created_at)
            sql = sql.format(created_col=", created_at", created_param=", ?")
        else:
            sql = sql.format(created_col="", created_param="")
        cur = db.execute(sql, tuple(params))
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    db.commit()
    return {
        "source_url": fetched["url"],
        "received": len(fetched["items"]),
        "inserted": inserted,
        "skipped": skipped,
        "inbound_seen": inbound,
        "outbound_seen": outbound,
    }
