import json
import os
import socket
from urllib.parse import urlparse

import requests


class OllamaService:
    def _candidate_urls(self, base_url="http://localhost:11434"):
        urls = []

        def add(url):
            if not url:
                return
            normalized = url.strip().rstrip("/")
            if normalized and normalized not in urls:
                urls.append(normalized)

        add(base_url)
        add(os.getenv("OLLAMA_BASE_URL"))

        fallback_raw = os.getenv(
            "OLLAMA_FALLBACK_BASE_URLS",
            "http://host.docker.internal:11434,http://172.17.0.1:11434,http://127.0.0.1:11434,http://localhost:11434",
        )
        for item in fallback_raw.split(","):
            add(item)

        parsed = urlparse(base_url or "")
        if parsed.hostname in ("localhost", "127.0.0.1"):
            add("http://host.docker.internal:11434")
            add("http://172.17.0.1:11434")
        elif parsed.hostname == "host.docker.internal":
            add("http://127.0.0.1:11434")
            add("http://172.17.0.1:11434")

        return urls

    def _preflight(self, base_url):
        parsed = urlparse(base_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=2):
                return None
        except OSError as exc:
            return f"{base_url} tidak bisa dijangkau ({exc})"

    def _request_json(self, method, endpoint, *, base_url, payload=None, timeout=(4, 20), stream=False):
        url = f"{base_url.rstrip('/')}{endpoint}"
        try:
            if method == "GET":
                response = requests.get(url, timeout=timeout, stream=stream)
            else:
                response = requests.post(url, json=payload, timeout=timeout, stream=stream)
            response.raise_for_status()
            return response
        except requests.Timeout as exc:
            raise RuntimeError(f"Ollama timeout di {base_url} saat akses {endpoint}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Gagal menghubungi Ollama {base_url}: {exc}") from exc

    def _pick_working_url(self, base_url, *, endpoint="/api/tags", payload=None, timeout=(4, 20), stream=False):
        errors = []
        for candidate in self._candidate_urls(base_url):
            preflight_error = self._preflight(candidate)
            if preflight_error:
                errors.append(preflight_error)
                continue
            try:
                response = self._request_json(
                    "POST" if payload is not None else "GET",
                    endpoint,
                    base_url=candidate,
                    payload=payload,
                    timeout=timeout,
                    stream=stream,
                )
                return candidate, response
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError("Tidak ada endpoint Ollama yang bisa diakses. " + " | ".join(errors))

    def list_models(self, base_url="http://localhost:11434"):
        candidate, response = self._pick_working_url(base_url, endpoint="/api/tags", timeout=(3, 12))
        data = response.json()
        models = data.get("models", []) if isinstance(data, dict) else []
        return [
            {
                "name": item.get("name"),
                "model": item.get("model") or item.get("name"),
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
                "resolved_base_url": candidate,
            }
            for item in models
            if item.get("name") or item.get("model")
        ]

    def generate(self, prompt, model, temperature=0.7, stream=False, base_url="http://localhost:11434"):
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": float(temperature)},
        }
        candidate, response = self._pick_working_url(
            base_url,
            endpoint="/api/generate",
            payload=payload,
            timeout=(4, 120),
        )
        data = response.json()
        return data.get("response", "")

    def generate_stream(self, prompt, model, temperature=0.7, base_url="http://localhost:11434"):
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": float(temperature)},
        }
        candidate, response = self._pick_working_url(
            base_url,
            endpoint="/api/generate",
            payload=payload,
            timeout=(4, 180),
            stream=True,
        )
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                yield data.get("response", ""), bool(data.get("done"))
        finally:
            response.close()


ollama_service = OllamaService()
