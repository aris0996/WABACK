import requests

from ..db import get_setting
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
