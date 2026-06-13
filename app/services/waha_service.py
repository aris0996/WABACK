import time
from urllib.parse import quote
import requests
from .settings_service import get_settings


class WahaService:
    def _config(self):
        settings = get_settings()
        return {
            "base_url": settings["waha_base_url"].rstrip("/"),
            "api_key": settings["waha_api_key"],
            "session": settings["waha_session"],
        }

    def _headers(self):
        return {"X-Api-Key": self._config()["api_key"], "Content-Type": "application/json"}

    def get_sessions(self):
        cfg = self._config()
        response = requests.get(f"{cfg['base_url']}/api/sessions", headers=self._headers(), timeout=15)
        response.raise_for_status()
        return response.json()

    def get_status(self):
        cfg = self._config()
        url = f"{cfg['base_url']}/api/sessions/{cfg['session']}"
        response = requests.get(url, headers=self._headers(), timeout=15)
        response.raise_for_status()
        return response.json()

    def get_chats(self, limit=100, offset=0):
        cfg = self._config()
        url = f"{cfg['base_url']}/api/{cfg['session']}/chats"
        response = requests.get(
            url,
            headers=self._headers(),
            params={"limit": limit, "offset": offset},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else data.get("data", data)

    def get_chat_messages(self, chat_id, limit=50, offset=0):
        cfg = self._config()
        safe_chat_id = quote(chat_id, safe="")
        url = f"{cfg['base_url']}/api/{cfg['session']}/chats/{safe_chat_id}/messages"
        response = requests.get(
            url,
            headers=self._headers(),
            params={"limit": limit, "offset": offset, "downloadMedia": "false"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else data.get("data", data)

    def send_text(self, chat_id, text):
        cfg = self._config()
        # WAHA installations may expose either /api/sendText or /api/{session}/sendText.
        payload = {"session": cfg["session"], "chatId": chat_id, "text": text}
        response = requests.post(f"{cfg['base_url']}/api/sendText", json=payload, headers=self._headers(), timeout=30)
        if response.status_code == 404:
            response = requests.post(
                f"{cfg['base_url']}/api/{cfg['session']}/sendText",
                json={"chatId": chat_id, "text": text},
                headers=self._headers(),
                timeout=30,
            )
        response.raise_for_status()
        return response.json() if response.text else {"ok": True}

    def send_typing(self, chat_id):
        return self._typing(chat_id, True)

    def stop_typing(self, chat_id):
        return self._typing(chat_id, False)

    def _typing(self, chat_id, enabled):
        cfg = self._config()
        payload = {"session": cfg["session"], "chatId": chat_id}
        endpoint = "startTyping" if enabled else "stopTyping"
        try:
            response = requests.post(f"{cfg['base_url']}/api/{endpoint}", json=payload, headers=self._headers(), timeout=10)
            if response.status_code == 404:
                return {"ok": False, "fallback": "typing endpoint unavailable"}
            response.raise_for_status()
            return response.json() if response.text else {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def human_delay(self, text):
        time.sleep(min(10, max(2, len(text or "") / 80)))


waha_service = WahaService()
