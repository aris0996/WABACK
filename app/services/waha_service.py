import requests

from ..db import execute, get_db, get_setting, query_one
from ..security import normalize_wa_number, validate_wa_number
from .network_service import tcp_probe


def _headers():
    api_key = get_setting("waha_api_key")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _base_url():
    return get_setting("waha_base_url").rstrip("/")


def send_message(wa_number, text):
    session = get_setting("waha_session", "default")
    payload = {"session": session, "chatId": f"{wa_number}@c.us", "text": text}
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


def _extract_chat_number(chat):
    chat_id = (
        chat.get("id")
        or chat.get("chatId")
        or chat.get("jid")
        or chat.get("conversationId")
        or ""
    )
    if isinstance(chat_id, dict):
        chat_id = chat_id.get("_serialized") or chat_id.get("user") or ""
    chat_id = str(chat_id)
    if "@g.us" in chat_id or chat_id == "status@broadcast":
        return ""
    return normalize_wa_number(chat_id)


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


def sync_contacts_from_waha(limit=200):
    fetched = fetch_chats(limit=limit)
    inserted = 0
    updated = 0
    skipped = 0
    db = get_db()
    for chat in fetched["items"]:
        if not isinstance(chat, dict):
            skipped += 1
            continue
        number = _extract_chat_number(chat)
        if not validate_wa_number(number):
            skipped += 1
            continue
        name = _extract_chat_name(chat)
        existing = query_one("SELECT id, display_name FROM contacts WHERE wa_number = ?", (number,))
        if existing:
            if name and name != existing["display_name"]:
                db.execute(
                    "UPDATE contacts SET display_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, existing["id"]),
                )
                updated += 1
            else:
                skipped += 1
        else:
            db.execute(
                """
                INSERT INTO contacts
                (wa_number, display_name, auto_reply_enabled, memory_generate_interval)
                VALUES (?, ?, ?, ?)
                """,
                (
                    number,
                    name,
                    1 if get_setting("default_contact_auto_reply", "true") == "true" else 0,
                    int(get_setting("memory_generate_interval", "20") or 20),
                ),
            )
            inserted += 1
    db.commit()
    return {
        "source_url": fetched["url"],
        "received": len(fetched["items"]),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }
