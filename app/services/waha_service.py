import os
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

    def _base_urls(self):
        cfg = self._config()
        urls = [cfg["base_url"]]
        extra = os.getenv("WAHA_FALLBACK_BASE_URLS", "http://127.0.0.1:3000,http://host.docker.internal:3000")
        for url in [item.strip().rstrip("/") for item in extra.split(",") if item.strip()]:
            if url not in urls:
                urls.append(url)
        return urls

    def _get_json(self, url, *, params=None, timeout=12):
        try:
            response = requests.get(url, headers=self._headers(), params=params, timeout=timeout)
        except requests.Timeout as exc:
            raise RuntimeError(f"WAHA timeout saat mengakses {url}. Cek waha_base_url, firewall, session, dan apakah WAHA hidup.") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Gagal menghubungi WAHA {url}: {exc}") from exc

        if response.status_code >= 400:
            body = response.text[:300] if response.text else ""
            raise RuntimeError(f"WAHA HTTP {response.status_code} untuk {url}. {body}")
        return response.json() if response.text else {}

    def _list_from_response(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "chats", "items", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def get_sessions(self):
        cfg = self._config()
        return self._get_json(f"{cfg['base_url']}/api/sessions", timeout=12)

    def get_status(self):
        cfg = self._config()
        errors = []
        for base_url in self._base_urls():
            try:
                return self._get_json(f"{base_url}/api/sessions/{cfg['session']}", timeout=8)
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError("Tidak bisa mengambil status WAHA. " + " | ".join(errors))

    def get_chats(self, limit=100, offset=0):
        cfg = self._config()
        params = {"limit": limit, "offset": offset}
        errors = []
        for base_url in self._base_urls():
            candidates = [
                (f"{base_url}/api/{cfg['session']}/chats", params),
                (f"{base_url}/api/chats", {**params, "session": cfg["session"]}),
            ]
            for url, request_params in candidates:
                try:
                    return self._list_from_response(self._get_json(url, params=request_params, timeout=8))
                except RuntimeError as exc:
                    errors.append(str(exc))
                    if "HTTP 404" not in str(exc):
                        break
        raise RuntimeError("Tidak bisa mengambil daftar chat WAHA. " + " | ".join(errors))

    def get_chat_messages(self, chat_id, limit=50, offset=0):
        cfg = self._config()
        safe_chat_id = quote(chat_id, safe="")
        errors = []
        for base_url in self._base_urls():
            url = f"{base_url}/api/{cfg['session']}/chats/{safe_chat_id}/messages"
            try:
                data = self._get_json(
                    url,
                    params={"limit": limit, "offset": offset, "downloadMedia": "false"},
                    timeout=8,
                )
                return self._list_from_response(data)
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError("Tidak bisa mengambil pesan chat WAHA. " + " | ".join(errors))

    def get_chat_picture(self, chat_id):
        cfg = self._config()
        safe_chat_id = quote(chat_id, safe="")
        errors = []
        for base_url in self._base_urls():
            candidates = [
                f"{base_url}/api/{cfg['session']}/chats/{safe_chat_id}/picture",
                f"{base_url}/api/contacts/profile-picture?session={cfg['session']}&id={safe_chat_id}",
            ]
            for url in candidates:
                try:
                    response = requests.get(url, headers=self._headers(), timeout=10, allow_redirects=True)
                    if response.status_code == 404:
                        continue
                    if response.status_code >= 400:
                        errors.append(f"{url} HTTP {response.status_code}")
                        continue
                    content_type = response.headers.get("Content-Type", "")
                    if content_type.startswith("image/"):
                        return response.content, content_type
                    try:
                        data = response.json()
                        if isinstance(data, dict):
                            avatar_url = data.get("url") or data.get("profilePicture") or data.get("picture")
                            if avatar_url:
                                image_response = requests.get(avatar_url, timeout=10)
                                image_response.raise_for_status()
                                return image_response.content, image_response.headers.get("Content-Type", "image/jpeg")
                    except Exception:
                        pass
                except Exception as exc:
                    errors.append(str(exc))
        raise RuntimeError("Tidak bisa mengambil avatar WAHA. " + " | ".join(errors[:4]))

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
