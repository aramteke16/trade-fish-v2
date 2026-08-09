"""DeepSeek adapter (default provider). OpenAI-compatible chat completions API."""

import requests

from tradefish import config

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def complete(prompt: str, model: str) -> tuple[str, int]:
    """Send one prompt, return (json_text, tokens_used)."""
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {config.get('DEEPSEEK_API_KEY')}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(config.get("LLM_TEMPERATURE", "0.0")),
            "response_format": {"type": "json_object"},
            "max_tokens": 1024,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data["usage"]["total_tokens"]
