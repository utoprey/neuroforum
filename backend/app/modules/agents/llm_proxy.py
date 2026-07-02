"""Thin LLM-call proxy used by the MCP server's ``llm_assist`` tool *and*
the ``ai_proposals`` service when generating real LLM suggestions.

Forwards a single prompt through the agent / user's BYO API key (Fernet-
decrypted at the call site, never persisted in plaintext). Currently only
OpenRouter is implemented end-to-end; ``cloud_ru`` raises
``NotImplementedError`` and is tracked as MVP-deferred.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Conservative default — long enough for any single chat completion call,
# short enough that a misbehaving upstream doesn't pin an MCP request.
_DEFAULT_TIMEOUT_S = 60.0


class LLMProxyError(Exception):
    """Upstream call failed in a way the caller should surface to the agent."""


async def call_openrouter(
    api_key: str,
    model: str,
    prompt: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> tuple[str, dict[str, Any]]:
    """POST to OpenRouter and return ``(text, usage_meta)``.

    ``usage_meta`` carries the data needed to write an
    :class:`LLMUsageLog` row: ``input_tokens``, ``output_tokens``,
    ``cost_usd`` (Decimal), and ``duration_ms``.
    """
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    # Optional but recommended by OpenRouter — they use it
                    # for analytics on the dashboard.
                    "X-Title": "Neuroforum-MCP",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    # Keep the request small enough to fit a free-tier
                    # OpenRouter credit balance — without an explicit cap
                    # the API requests the model's full context (64k+) and
                    # rejects the call with HTTP 402 even for short prompts.
                    "max_tokens": 1024,
                },
            )
        except httpx.HTTPError as exc:
            raise LLMProxyError(f"OpenRouter request failed: {exc}") from exc

    duration_ms = int((time.monotonic() - start) * 1000)

    if response.status_code >= 400:
        # Surface upstream error verbatim — the agent's owner needs to see
        # the exact reason (bad model, quota, ratelimit, etc.).
        raise LLMProxyError(
            f"OpenRouter {response.status_code}: {response.text[:500]}"
        )

    data = response.json()
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProxyError(
            f"Malformed OpenRouter response (no choices/message): {data!r}"
        ) from exc

    usage = data.get("usage") or {}
    # OpenRouter sometimes reports cost under "total_cost"; sometimes not
    # at all. Be defensive — Decimal('0') beats KeyError every time.
    raw_cost = usage.get("total_cost") or data.get("cost") or 0
    try:
        cost = Decimal(str(raw_cost))
    except Exception:
        # Keep accounting bulletproof — log lines and budgets stay accurate
        # even if the upstream returns a weirdly-shaped cost field.
        cost = Decimal("0")
    return text, {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "cost_usd": cost,
        "duration_ms": duration_ms,
    }


async def call_provider(
    provider: str,
    api_key: str,
    model: str,
    prompt: str,
) -> tuple[str, dict[str, Any]]:
    """Dispatch to the appropriate provider client.

    Only ``openrouter`` is fully implemented in MVP. ``cloud_ru`` returns a
    deterministic NotImplementedError so callers see a clean failure
    rather than a vague upstream error.
    """
    if provider == "openrouter":
        return await call_openrouter(api_key, model, prompt)
    if provider == "cloud_ru":
        raise NotImplementedError(
            "cloud_ru provider is deferred beyond MVP — track in TODO"
        )
    raise LLMProxyError(f"Unknown LLM provider: {provider!r}")


__all__ = ["LLMProxyError", "call_openrouter", "call_provider"]
