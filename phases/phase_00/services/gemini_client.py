"""LLM client adapter — Emergent universal key (OpenAI-compatible proxy).

Routes Gemini calls through https://integrations.emergentagent.com/llm when
EMERGENT_LLM_KEY is set (no 20 req/day free-tier cap); falls back to the
direct google-genai SDK with GEMINI_API_KEY otherwise.

Exposes the same minimal surface the agents already use
(`generate_content` / `generate_content_async` with a generation_config dict
and a `.text` response attribute), so call sites and test mocks stay unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from phases.phase_00.config import get_settings

EMERGENT_BASE_URL = "https://integrations.emergentagent.com/llm/v1/chat/completions"
# gemini-2.0-flash was retired upstream; 2.5-flash is the current equivalent.
# LiteLLM-prefixed name as listed by the proxy's /v1/models.
DEFAULT_MODEL = "gemini/gemini-2.5-flash"
_TIMEOUT = 30.0


class _Response:
    """Minimal response wrapper — callers only use `.text`."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


def _build_payload(model: str, contents: Any, generation_config: dict | None) -> dict:
    """Map google-genai style (contents, generation_config) → OpenAI chat payload."""
    cfg = generation_config or {}

    # contents: str → one user message; list → [system, user, ...] (persona style)
    if isinstance(contents, str):
        messages = [{"role": "user", "content": contents}]
    else:
        parts = [str(c) for c in contents]
        messages = []
        if len(parts) > 1:
            messages.append({"role": "system", "content": parts[0]})
            parts = parts[1:]
        for p in parts:
            messages.append({"role": "user", "content": p})

    payload: dict = {"model": model, "messages": messages}

    if "temperature" in cfg:
        payload["temperature"] = cfg["temperature"]

    # JSON mode; response_schema can't be passed natively through the proxy,
    # so append it to the prompt — Pydantic still validates downstream.
    if cfg.get("response_mime_type") == "application/json":
        payload["response_format"] = {"type": "json_object"}
        schema = cfg.get("response_schema")
        if schema:
            messages[-1]["content"] += (
                "\nReturn ONLY valid JSON matching this schema:\n"
                + json.dumps(schema)
            )

    # Give JSON responses headroom — thinking models (gemini-2.5-*) burn
    # reasoning tokens inside max_tokens, so a small cap truncates the JSON.
    max_tokens = cfg.get("max_output_tokens")
    if max_tokens:
        payload["max_tokens"] = max(int(max_tokens), 4096)

    return payload


def _extract_text(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected proxy response: {str(data)[:200]}")


class GeminiModel:
    """Drop-in replacement for the old genai.GenerativeModel."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        settings = get_settings()
        self._emergent_key = settings.emergent_llm_key
        self._model = model
        if not self._emergent_key:
            # Fallback: direct google-genai SDK
            from google import genai
            self._direct = genai.Client(api_key=api_key or settings.gemini_api_key)
        else:
            self._direct = None

    # ── Emergent proxy path ────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._emergent_key}",
            "Content-Type": "application/json",
        }

    def generate_content(self, contents: Any, generation_config: dict | None = None):
        if self._direct is not None:
            return self._direct.models.generate_content(
                model="gemini-2.5-flash-lite", contents=contents,
                config=generation_config or None,
            )
        payload = _build_payload(self._model, contents, generation_config)
        resp = httpx.post(EMERGENT_BASE_URL, headers=self._headers(), json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return _Response(_extract_text(resp.json()))

    async def generate_content_async(self, contents: Any, generation_config: dict | None = None):
        if self._direct is not None:
            return await self._direct.aio.models.generate_content(
                model="gemini-2.5-flash-lite", contents=contents,
                config=generation_config or None,
            )
        payload = _build_payload(self._model, contents, generation_config)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(EMERGENT_BASE_URL, headers=self._headers(), json=payload)
            resp.raise_for_status()
            return _Response(_extract_text(resp.json()))
