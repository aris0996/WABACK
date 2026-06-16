import json

import requests

from ..db import get_setting


def _base_url():
    return get_setting("ollama_base_url").rstrip("/")


def generate(model, prompt, temperature="0.2"):
    response = requests.post(
        f"{_base_url()}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": float(temperature or 0.2)},
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


def generate_json(model, prompt, temperature="0.1"):
    text = generate(model, prompt, temperature)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def test_connection():
    response = requests.get(f"{_base_url()}/api/tags", timeout=10)
    response.raise_for_status()
    return response.json()
