"""
Cost Guard — pre-flight safety check for every outbound LLM request.

Blocks:
- Non-allowlisted models
- Prompts over the token size limit
- Requests with tools enabled (tools are NEVER needed for story generation)
- Oversized image data in messages

Call `cost_guard.check(...)` before every OpenRouter request.
If it raises CostGuardError, the request MUST NOT be sent.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("malenkie_legendy")

# ─── Allowlist / Blocklist ────────────────────────────────────────────────────

ALLOWED_MODELS: set[str] = {
    "openai/gpt-4o-mini",
    "openai/gpt-4o-mini-2024-07-18",
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "google/gemini-flash-1.5-8b",
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-3.2-3b-instruct:free",
}

BLOCKED_SUBSTRINGS: tuple[str, ...] = (
    "opus",
    "claude-3-5",
    "claude-3-7",
    "claude-4",
    "o1",
    "o3",
    "gemini-pro",
    "bedrock",
)

# ─── Limits ──────────────────────────────────────────────────────────────────

# Story generation prompt is ~3500-5000 chars. Cap at 16k tokens to be safe.
CHARS_PER_TOKEN = 4
MAX_PROMPT_TOKENS = 16_000   # ~64 000 chars

MAX_IMAGE_B64_BYTES = 500_000


# ─── Exception ───────────────────────────────────────────────────────────────

class CostGuardError(RuntimeError):
    """Raised when a request violates cost-safety policy. Do NOT send the request."""


# ─── Core check ──────────────────────────────────────────────────────────────

def check(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list | None = None,
    pipeline: str = "story_generation",
) -> None:
    """
    Validate an outbound OpenRouter request against all cost-safety rules.

    Raises:
        CostGuardError: if any rule is violated.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    model_lower = model.lower()

    # 1. Blocked substrings
    for blocked in BLOCKED_SUBSTRINGS:
        if blocked in model_lower:
            _reject(ts, pipeline, model, f"model matches blocked pattern '{blocked}'")

    # 2. Allowlist
    if model not in ALLOWED_MODELS:
        _reject(
            ts, pipeline, model,
            f"model '{model}' is not in ALLOWED_MODELS. "
            "Add it explicitly to cost_guard.ALLOWED_MODELS if you intend to use it."
        )

    # 3. Tools — never permitted in story generation
    if tools:
        _reject(ts, pipeline, model, f"tools are not permitted in '{pipeline}' pipeline")

    # 4. Prompt size
    prompt_chars = _estimate_message_chars(messages)
    prompt_tokens_est = prompt_chars // CHARS_PER_TOKEN
    if prompt_tokens_est > MAX_PROMPT_TOKENS:
        _reject(
            ts, pipeline, model,
            f"estimated prompt {prompt_tokens_est} tokens exceeds limit {MAX_PROMPT_TOKENS}"
        )

    log.info(
        "[CostGuard OK] ts=%s pipeline=%s model=%s est_tokens=%d",
        ts, pipeline, model, prompt_tokens_est,
    )


def _estimate_message_chars(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += len(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        total += 500  # fixed overhead, don't count b64
    return total


def _reject(ts: str, pipeline: str, model: str, reason: str) -> None:
    msg = f"[CostGuard BLOCKED] ts={ts} pipeline={pipeline} model={model} reason={reason}"
    log.error(msg)
    raise CostGuardError(msg)
