from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class LLMClient:
    """Small OpenAI-compatible wrapper.

    The app still starts without an API key. In that case `available` is false
    and callers use deterministic fallbacks for parsing and recommendation text.
    """

    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "deepseek-chat").strip()
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com").strip()
        self.available = bool(api_key)
        self.base_url = base_url if base_url else "default"
        self.client = OpenAI(api_key=api_key, base_url=base_url or None) if api_key else None

    def complete(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def health_check(self) -> str:
        return self.complete("You are a health check endpoint.", "Reply with OK only.", temperature=0)

    def json_complete(self, system: str, user: str) -> dict[str, Any]:
        text = self.complete(system, user, temperature=0.1)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Model did not return a JSON object.")
        return json.loads(text[start : end + 1])


llm_client = LLMClient()
