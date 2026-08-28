"""
Fixes for two related LiteLLM /v1/messages data-loss bugs affecting Claude
Code CLI traffic to openai/-prefixed backends:

1. Content blocks whose `type` isn't exactly "text" (e.g. "input_text"/
   "output_text") are silently dropped by litellm's Anthropic->OpenAI
   translators (adapters/transformation.py and
   responses_adapters/transformation.py both only recognize `type == "text"`).
   Matches upstream issue https://github.com/BerriAI/litellm/issues/23841.

2. Messages with `"role": "system"` injected mid-conversation (Claude Code's
   own convention for dynamically-updated content like the available-skills
   listing, available-agent-types listing, and token-budget reminders -- kept
   out of the main cached system block so that block stays stable across
   turns for prompt-caching purposes) are silently dropped entirely.
   Anthropic's real Messages API only allows "user"/"assistant" roles in the
   `messages` array; litellm's translate_anthropic_messages_to_openai() has
   no branch for any other role, so the whole message -- e.g. the entire
   skills listing -- never reaches the backend model, with no error surfaced.
   Confirmed by capturing a real Claude Code v2.1.241 request: the full
   10-skill listing was present verbatim in one such message, which is
   exactly why the model could never report on it when asked "list your
   skills" through this proxy, despite reporting correctly when the same
   content was injected as top-level `system` text.

Both are confirmed directly against this proxy (litellm 1.82.6, image built
2026-08-26), independent of the Responses-API-vs-chat/completions routing
choice (both paths share bug 1's flaw; bug 2 lives in the shared
message-translation code both paths, and the earlier thinking-block fix,
call into).

This uses litellm's documented CustomLogger.async_pre_call_hook extension
point (https://docs.litellm.ai/docs/observability/custom_callback) to fix
the raw request body before any of litellm's lossy translation code runs --
so it doesn't require patching litellm's own (mutable-tag, upstream-owned)
source files, which would need re-syncing on every image pull.
"""

from typing import Any, List, Optional

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


def _content_to_text_blocks(content: Any) -> List[dict]:
    """Flatten a message's `content` (str or block list) into text blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        blocks = []
        for b in content:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                blocks.append({"type": "text", "text": b["text"]})
        return blocks
    return []


def _fold_system_role_messages(data: dict) -> None:
    """Move mid-conversation role="system" messages into the top-level
    `system` field, since Anthropic's spec doesn't define that role for the
    `messages` array and litellm silently drops messages it doesn't
    recognize the role of."""
    messages = data.get("messages")
    if not isinstance(messages, list):
        return

    kept: List[Any] = []
    extra_system_blocks: List[dict] = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            extra_system_blocks.extend(_content_to_text_blocks(m.get("content")))
        else:
            kept.append(m)

    if not extra_system_blocks:
        return

    data["messages"] = kept
    system = data.get("system")
    if system is None:
        data["system"] = extra_system_blocks
    elif isinstance(system, str):
        data["system"] = (
            [{"type": "text", "text": system}] if system else []
        ) + extra_system_blocks
    elif isinstance(system, list):
        data["system"] = system + extra_system_blocks


class AnthropicInputTextBlockFix(CustomLogger):
    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type: Optional[str] = None,
    ) -> Optional[dict]:
        _fold_system_role_messages(data)

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
