"""
Fix for LiteLLM silently dropping Anthropic /v1/messages content blocks whose
`type` isn't exactly "text" (e.g. "input_text"/"output_text", which newer
Claude Code CLI versions send for parts of the system prompt and message
history) when translating requests for openai/-prefixed backends.

Root cause: litellm's Anthropic->OpenAI translators
(litellm/llms/anthropic/experimental_pass_through/adapters/transformation.py
and .../responses_adapters/transformation.py) only recognize `type == "text"`
content blocks. Anything else is silently discarded before the request ever
reaches the backend model, with no error surfaced to the client. Confirmed
directly against this proxy (litellm 1.82.6, image built 2026-08-26) and
matches upstream issue https://github.com/BerriAI/litellm/issues/23841.

This uses litellm's documented CustomLogger.async_pre_call_hook extension
point (https://docs.litellm.ai/docs/observability/custom_callback) to
normalize these block types to "text" on the raw request body, before any
of litellm's lossy translation code runs -- so it isn't tied to the
chat/completions vs. Responses API routing choice, and doesn't require
patching litellm's own (mutable-tag, upstream-owned) source files.
"""

from typing import Any, Optional

from litellm.integrations.custom_logger import CustomLogger

# Anthropic's real Messages API only defines "text" for text content blocks.
# These are the non-conformant type names known to appear from Claude Code
# CLI that carry a "text" field and should be treated as plain text blocks.
_TEXT_ALIASES = {"input_text", "output_text"}


def _normalize_block(block: Any) -> Any:
    if (
        isinstance(block, dict)
        and block.get("type") in _TEXT_ALIASES
        and "text" in block
    ):
        block = dict(block)
        block["type"] = "text"
    return block


def _normalize_content(content: Any) -> Any:
    if isinstance(content, list):
        return [_normalize_block(b) for b in content]
    return content


class AnthropicInputTextBlockFix(CustomLogger):
    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type: Optional[str] = None,
    ) -> Optional[dict]:
        system = data.get("system")
        if isinstance(system, list):
            data["system"] = _normalize_content(system)

        messages = data.get("messages")
        if isinstance(messages, list):
            for m in messages:
                if isinstance(m, dict) and "content" in m:
                    m["content"] = _normalize_content(m["content"])

        return data


proxy_handler_instance = AnthropicInputTextBlockFix()
