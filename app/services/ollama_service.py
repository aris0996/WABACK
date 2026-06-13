import json
import requests


class OllamaService:
    def list_models(self, base_url="http://localhost:11434"):
        try:
            response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=12)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise RuntimeError(f"Ollama timeout di {base_url}. Pastikan Ollama hidup dan bisa diakses backend.") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Gagal menghubungi Ollama {base_url}: {exc}") from exc

        models = data.get("models", []) if isinstance(data, dict) else []
        return [
            {
                "name": item.get("name"),
                "model": item.get("model") or item.get("name"),
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
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
        try:
            response = requests.post(f"{base_url.rstrip('/')}/api/generate", json=payload, timeout=120)
            response.raise_for_status()
        except requests.Timeout as exc:
            raise RuntimeError(f"Ollama timeout saat generate dengan model {model}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama generate gagal untuk model {model}: {exc}") from exc
        return response.json().get("response", "")

    def generate_stream(self, prompt, model, temperature=0.7, base_url="http://localhost:11434"):
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": float(temperature)},
        }
        with requests.post(f"{base_url.rstrip('/')}/api/generate", json=payload, stream=True, timeout=180) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                yield data.get("response", ""), bool(data.get("done"))


ollama_service = OllamaService()
