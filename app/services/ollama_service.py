import json

import requests

from ..db import get_setting
from .network_service import tcp_probe


def _base_url():
    return get_setting("ollama_base_url").rstrip("/")


def _settings_int(key, default):
    try:
        return int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return default


def generate(model, prompt, temperature="0.2", num_predict=None):
    options = {"temperature": float(temperature or 0.2)}
    if num_predict is not None:
        options["num_predict"] = max(1, int(num_predict))
    response = requests.post(
        f"{_base_url()}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": get_setting("ollama_keep_alive", "30s"),
            "options": options,
        },
        timeout=_settings_int("ollama_request_timeout", 120),
    )
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


def generate_json(model, prompt, temperature="0.1", num_predict=None):
    text = generate(model, prompt, temperature, num_predict=num_predict)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def test_connection():
    base = _base_url()
    probe = tcp_probe(base)
    if not probe["ok"]:
        raise RuntimeError({"probe": probe, "url": f"{base}/api/tags"})
    response = requests.get(f"{base}/api/tags", timeout=10)
    response.raise_for_status()
    return {"url": f"{base}/api/tags", "probe": probe, "result": response.json()}
