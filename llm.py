"""
Thin wrapper around LLM providers.
Set LLM_PROVIDER=anthropic (default) or LLM_PROVIDER=gemini.
If unset, auto-detects based on which API key is present.

Model names are read from config.json (keys: anthropic_model, gemini_model).
"""
import json
import os
from pathlib import Path

from fastapi import HTTPException

_CONFIG_PATH = Path(__file__).parent / "config.json"
_DEFAULTS = {
    "anthropic_model": "claude-opus-5-5",
    "gemini_model":    "gemini-3.8-flash",
}


_MAX_PAUSE_CONTINUATIONS = 5


def _cfg(key: str) -> str:
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return data.get(key) or _DEFAULTS[key]
    except Exception:
        return _DEFAULTS[key]


def complete(prompt: str, use_search: bool = True) -> str:
    provider = _resolve_provider()

    try:
        if provider == "anthropic":
            return _anthropic(prompt, use_search)
        else:
            return _gemini(prompt, use_search)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"LLM call failed: {exc}") from exc


def _resolve_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "").lower()
    if provider in ("anthropic", "gemini"):
        return provider
    # Auto-detect from whichever key is present
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    raise HTTPException(
        500,
        "No API key found. Set ANTHROPIC_API_KEY or GEMINI_API_KEY "
        "(and optionally LLM_PROVIDER=anthropic|gemini)."
    )


def _anthropic(prompt: str, use_search: bool) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(500, "ANTHROPIC_API_KEY is not set.")
    import anthropic
    client = anthropic.Anthropic(api_key=key)

    extra = {}
    if use_search:
        extra["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    messages = [{"role": "user", "content": prompt}]
    for _ in range(_MAX_PAUSE_CONTINUATIONS):
        message = client.beta.messages.create(
            model=_cfg("anthropic_model"),
            # Thinking is always on and counts toward max_tokens.
            max_tokens=16000,
            output_config={"effort": "medium"},
            # On a safety-classifier decline, re-run on Anthropic's
            # recommended fallback model instead of returning nothing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=messages,
            **extra,
        )
        # A long web-search turn can pause; resend it to let Claude continue.
        if message.stop_reason != "pause_turn":
            break
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": message.content},
        ]

    if message.stop_reason == "refusal":
        raise HTTPException(502, "Claude declined this request.")
    # Collect all text blocks (web search may add non-text blocks)
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


def _gemini(prompt: str, use_search: bool) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(500, "GEMINI_API_KEY is not set.")
    from google import genai
    client = genai.Client(api_key=key)

    extra = {"tools": [{"type": "google_search"}]} if use_search else {}
    interaction = client.interactions.create(
        model=_cfg("gemini_model"),
        input=prompt,
        store=False,
        **extra,
    )
    return interaction.output_text or ""
