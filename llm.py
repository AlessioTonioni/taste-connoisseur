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
    "anthropic_model": "claude-opus-4-6",
    "gemini_model":    "gemini-3-flash-preview",
}


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
    client  = anthropic.Anthropic(api_key=key)
    
    tools = [{"type": "web_search_20250305", "name": "web_search"}] if use_search else []
    
    message = client.messages.create(
        model=_cfg("anthropic_model"),
        max_tokens=1024,
        tools=tools if tools else anthropic.NOT_GIVEN,
        messages=[{"role": "user", "content": prompt}],
    )
    # Collect all text blocks (web search may add non-text blocks)
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


def _gemini(prompt: str, use_search: bool) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(500, "GEMINI_API_KEY is not set.")
    from google import genai
    from google.genai import types
    client   = genai.Client(api_key=key)
    
    config = None
    if use_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

    response = client.models.generate_content(
        model=_cfg("gemini_model"),
        contents=prompt,
        config=config,
    )
    return response.text
