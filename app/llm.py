"""One function, chat(), used by every agent and by the ranker/summariser.

Works with any OpenAI-compatible endpoint (Groq, Gemini, Ollama, OpenRouter...).
With LLM_PROVIDER=mock no network calls are made: see app/mock.py.
"""
import json
import re
import threading
import time
from collections import defaultdict

from . import config

_client = None
_lock = threading.Lock()
_last_call = 0.0
_usage = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})


class LLMError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            max_retries=config.LLM_MAX_RETRIES,  # SDK backs off on 429 / 5xx
            timeout=120,
        )
    return _client


def _throttle():
    global _last_call
    with _lock:
        wait = config.LLM_MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def chat(messages, *, purpose, meter=None, mock_ctx=None, max_tokens=1800):
    """Return the assistant's text. `purpose` names the caller (planner, coder, ranker, summary)."""
    if config.LLM_PROVIDER == "mock":
        from . import mock

        text = mock.respond(purpose, mock_ctx or {})
        if meter:
            _usage[meter]["calls"] += 1
        return text

    _throttle()
    kwargs = dict(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=max_tokens,
    )
    if config.LLM_REASONING_EFFORT:
        kwargs["reasoning_effort"] = config.LLM_REASONING_EFFORT
    try:
        resp = _get_client().chat.completions.create(**kwargs)
    except Exception as exc:  # surface a readable message in the UI
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc

    text = (resp.choices[0].message.content or "").strip()
    if meter and resp.usage:
        u = _usage[meter]
        u["calls"] += 1
        u["prompt_tokens"] += resp.usage.prompt_tokens or 0
        u["completion_tokens"] += resp.usage.completion_tokens or 0
    return text


def usage(meter):
    return dict(_usage.get(meter, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}))


def extract_json(text):
    """Pull the first JSON object out of a model reply (handles ``` fences and chatter)."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)
    return None
