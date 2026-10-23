#!/usr/bin/env python3
"""
Agentic Capability Test — Thinking, Reasoning, and Tool Calling
================================================================
Exercises a served model through LiteLLM (or directly against a vLLM engine,
via --base-url) the same way an agentic coding
harness (opencode, Cline, Claude Code) actually uses it: OpenAI-compatible
/v1/chat/completions, a realistic multi-tool palette, multi-turn tool-result
context, and streaming. Each test is independent and reports pass/fail/warn
with the actual request/response detail needed to diagnose a failure.

Covers:
  1. Connectivity           - basic non-tool completion
  2. Reasoning presence     - thinking pass fires and reaches a correct answer
  3. Small-budget risk      - regression check for the known "small max_tokens
                              can return empty content" behavior of reasoning
                              models (see docker-compose.qwen3.8.yml's
                              SIMPLIFICATION PASS note) — reported as a
                              warning, not a failure, since it's a known/
                              accepted tradeoff, not a bug this script is
                              meant to catch as new.
  4. Single tool call       - one unambiguous prompt, one correct tool
  5. Tool selection breadth - one prompt per tool in the palette
  6. Multi-turn tool context - a synthetic tool result must actually be used
                              in the next tool call (the real test of whether
                              an agentic loop like Cline's would work)
  7. No hallucinated calls  - a prompt with no matching tool must NOT invent one
  8. Streaming reconstruction - tool_calls delta chunks must reassemble into
                              valid JSON (a real code path Cline/opencode use
                              that a non-streaming test would miss)
  9. Vision                 - a generated solid-red 64x64 PNG (stdlib zlib+struct,
                              sent as a data: URI image_url part) must be
                              described as "red" (whole word, in the final
                              content, not the reasoning; another basic colour
                              word without "red" is a FAIL). The colour is
                              fixed, so a model could guess it: this proves the
                              endpoint accepts and processes images, not
                              fine-grained vision. A text-only model/endpoint
                              that rejects images (HTTP 4xx other than 401/403,
                              or an error mentioning image/vision/multimodal)
                              gets a WARN, not a FAIL; use --skip-vision to
                              leave the test out entirely.
 10. Decode throughput      - one generation (max_tokens 1024); reports
                              completion_tokens, finish_reason, wall time and
                              tok/s. The count INCLUDES reasoning tokens and
                              the wall time includes prefill/TTFT, so a
                              reasoning model usually hits the 1024 cap
                              (finish_reason=length). Purely informational:
                              PASS whenever tokens were produced, never fails
                              on speed.

Usage:
    python3 test-agentic-capabilities.py [--base-url URL] [--api-key KEY]
                                          [--model MODEL] [--output FILE] [--skip-vision]

Example:
    # default model: qwen3.8-flash-next (Flash-Next, the default stack since 2026-10-22)
    python3 scripts/test-agentic-capabilities.py
    # Qwen3.8-27B (ROLLBACK stack; restore the ROLLBACK blocks in litellm-config.yaml first):
    python3 scripts/test-agentic-capabilities.py --model qwen3.8-27b
    # through agentgateway:
    python3 scripts/test-agentic-capabilities.py --base-url http://localhost:4100/v1
    # ...or directly against the engine (vLLM has no --api-key, any token works):
    python3 scripts/test-agentic-capabilities.py --base-url http://localhost:8301/v1 --model qwen3.8-flash-next
    python3 scripts/test-agentic-capabilities.py --model qwen3.6-35b-a3b --output ai-workspace/reports/agentic-test-qwen36.json
"""

import argparse
import base64
import json
import os
import re
import struct
import sys
import time
import urllib.request
import urllib.error
import zlib
from pathlib import Path

DEFAULT_BASE_URL = "http://localhost:4000/v1"
DEFAULT_MODEL = "qwen3.8-flash-next"
REQUEST_TIMEOUT = 120  # seconds per request


# =============================================================================
# Tool palette — mirrors a realistic coding-agent tool set (search/read/write/
# execute), the same shape this project's own history used to verify qwen3.6's
# qwen3_coder parser (docker-compose.qwen3.6.yml corrections item 19).
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search the codebase for a symbol, function, or text pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (symbol name, regex, or text)"},
                    "path": {"type": "string", "description": "Optional directory to restrict the search to"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a NEW file, or overwrite an EXISTING file, with the given full "
                "content. This is the correct tool any time the task is to create or "
                "rewrite a file. Do not use execute_command with shell redirection "
                "(echo/cat/heredoc) for file creation or edits — use this tool instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": (
                "Run a shell command — for things like running tests, builds, git "
                "operations, or search utilities (grep/find/ls). Do NOT use this to "
                "create or edit files; use write_file or read_file for file operations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
]


# =============================================================================
# HTTP helper (stdlib only, matching this project's gpu-power-benchmark.py)
# =============================================================================

def chat_completion(base_url, api_key, model, messages, tools=None, tool_choice=None,
                     max_tokens=512, temperature=None, stream=False):
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    if temperature is not None:
        payload["temperature"] = temperature

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    if not stream:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # Streaming: reconstruct content + tool_calls from SSE "data: {...}" chunks
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        content_parts = []
        tool_call_frags = {}  # index -> {"id":..., "name":..., "arguments": "..."}
        finish_reason = None
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line or not line.startswith("data:"):
                continue
            payload_str = line[len("data:"):].strip()
            if payload_str == "[DONE]":
                break
            chunk = json.loads(payload_str)
            # agentgateway ends a stream with a usage-only chunk whose choices is []
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta", {})
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            if delta.get("content"):
                content_parts.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                frag = tool_call_frags.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                if tc.get("id"):
                    frag["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    frag["name"] = fn["name"]
                if fn.get("arguments"):
                    frag["arguments"] += fn["arguments"]

        reconstructed_tool_calls = [
            {"id": f["id"], "function": {"name": f["name"], "arguments": f["arguments"]}}
            for f in tool_call_frags.values()
        ]
        return {
            "_streamed": True,
            "choices": [{
                "finish_reason": finish_reason,
                "message": {
                    "content": "".join(content_parts) or None,
                    "tool_calls": reconstructed_tool_calls or None,
                },
            }],
        }


def get_tool_calls(response):
    msg = response.get("choices", [{}])[0].get("message", {})
    return msg.get("tool_calls") or []


def get_content(response):
    msg = response.get("choices", [{}])[0].get("message", {})
    return msg.get("content")


def get_reasoning(response):
    msg = response.get("choices", [{}])[0].get("message", {})
    return msg.get("reasoning_content") or msg.get("reasoning")


# =============================================================================
# Test cases — each returns (name, status, detail) where status is
# "PASS" / "FAIL" / "WARN"
# =============================================================================

def test_connectivity(base_url, api_key, model):
    try:
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "Reply with exactly: pong"}],
            max_tokens=200,
        )
        content = get_content(resp)
        if content and "pong" in content.lower():
            return "Connectivity", "PASS", f"Got response: {content!r}"
        return "Connectivity", "WARN", f"Responded but unexpected content: {content!r}"
    except Exception as e:
        return "Connectivity", "FAIL", f"{type(e).__name__}: {e}"


def test_reasoning_present(base_url, api_key, model):
    try:
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "What is 17 * 24? Think it through, then give just the final number on the last line."}],
            max_tokens=600,
        )
        reasoning = get_reasoning(resp)
        content = get_content(resp) or ""
        reasoning_tokens = (
            resp.get("usage", {}).get("completion_tokens_details", {}) or {}
        ).get("reasoning_tokens", 0)
        correct = "408" in content
        if reasoning or reasoning_tokens:
            status = "PASS" if correct else "WARN"
            detail = f"reasoning_tokens={reasoning_tokens}, correct_answer={correct}, content_tail={content[-60:]!r}"
            return "Reasoning presence", status, detail
        return "Reasoning presence", "WARN", f"No reasoning detected (reasoning_tokens={reasoning_tokens}) — thinking may be disabled"
    except Exception as e:
        return "Reasoning presence", "FAIL", f"{type(e).__name__}: {e}"


def test_small_budget_reasoning_risk(base_url, api_key, model):
    try:
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=20,
        )
        content = get_content(resp)
        finish_reason = resp.get("choices", [{}])[0].get("finish_reason")
        if not content and finish_reason == "length":
            return ("Small-budget reasoning risk", "WARN",
                    "Known behavior reproduced: max_tokens=20 returned empty content "
                    "(all tokens spent on reasoning). Not a new bug — a known trait "
                    "of reasoning models (see the SIMPLIFICATION PASS note in "
                    "docker-compose.qwen3.8.yml). "
                    "Flag this to harness authors if they use small per-call token budgets.")
        return "Small-budget reasoning risk", "PASS", f"content={content!r}, finish_reason={finish_reason}"
    except Exception as e:
        return "Small-budget reasoning risk", "FAIL", f"{type(e).__name__}: {e}"


def test_single_tool_call(base_url, api_key, model):
    try:
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "Read the contents of the file src/app.py"}],
            tools=TOOLS, tool_choice="auto", max_tokens=400,
        )
        calls = get_tool_calls(resp)
        if len(calls) != 1:
            return "Single tool call", "FAIL", f"Expected 1 tool call, got {len(calls)}: {calls}"
        fn = calls[0]["function"]
        if fn["name"] != "read_file":
            return "Single tool call", "FAIL", f"Expected read_file, got {fn['name']!r}"
        try:
            args = json.loads(fn["arguments"])
        except json.JSONDecodeError as e:
            return "Single tool call", "FAIL", f"Arguments not valid JSON: {fn['arguments']!r} ({e})"
        if "app.py" not in args.get("path", ""):
            return "Single tool call", "WARN", f"Tool/name correct but path looks off: {args}"
        return "Single tool call", "PASS", f"read_file({args})"
    except Exception as e:
        return "Single tool call", "FAIL", f"{type(e).__name__}: {e}"


TOOL_SELECTION_CASES = [
    ("Find every place the function `handleSubmit` is called in the codebase", "search_code"),
    ("Show me what's in package.json", "read_file"),
    ("Create a new file called utils/helpers.js with an empty export default {}", "write_file"),
    ("Run the test suite with npm test", "execute_command"),
]


def test_tool_selection_breadth(base_url, api_key, model):
    results = []
    for prompt, expected_tool in TOOL_SELECTION_CASES:
        try:
            resp = chat_completion(
                base_url, api_key, model,
                messages=[{"role": "user", "content": prompt}],
                tools=TOOLS, tool_choice="auto", max_tokens=400,
            )
            calls = get_tool_calls(resp)
            if not calls:
                results.append((prompt, "FAIL", "No tool call made"))
                continue
            got = calls[0]["function"]["name"]
            if got == expected_tool:
                results.append((prompt, "PASS", got))
            else:
                results.append((prompt, "FAIL", f"expected {expected_tool}, got {got}"))
        except Exception as e:
            results.append((prompt, "FAIL", f"{type(e).__name__}: {e}"))

    failures = [r for r in results if r[1] == "FAIL"]
    status = "PASS" if not failures else "FAIL"
    detail = "; ".join(f"[{'OK' if s == 'PASS' else 'X'}] {p[:40]}... -> {d}" for p, s, d in results)
    return f"Tool selection breadth ({len(results)-len(failures)}/{len(results)})", status, detail


def test_multiturn_tool_context(base_url, api_key, model):
    """The real agentic-loop test: does a tool result from turn 1 actually
    inform the tool call made in turn 2? This is what Cline/opencode depend
    on for every multi-step task."""
    try:
        turn1 = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "Find where the class TodoList is defined"}],
            tools=TOOLS, tool_choice="auto", max_tokens=400,
        )
        calls1 = get_tool_calls(turn1)
        if not calls1 or calls1[0]["function"]["name"] != "search_code":
            return "Multi-turn tool context", "FAIL", f"Turn 1 didn't call search_code: {calls1}"

        synthetic_tool_result = json.dumps({
            "matches": [{"file": "src/components/TodoList.jsx", "line": 12,
                         "snippet": "export class TodoList extends Component {"}]
        })

        messages = [
            {"role": "user", "content": "Find where the class TodoList is defined"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": calls1[0].get("id", "call_1"), "type": "function",
                 "function": calls1[0]["function"]}
            ]},
            {"role": "tool", "tool_call_id": calls1[0].get("id", "call_1"),
             "content": synthetic_tool_result},
            {"role": "user", "content": "Now read that entire file."},
        ]
        turn2 = chat_completion(
            base_url, api_key, model,
            messages=messages, tools=TOOLS, tool_choice="auto", max_tokens=400,
        )
        calls2 = get_tool_calls(turn2)
        if not calls2 or calls2[0]["function"]["name"] != "read_file":
            return "Multi-turn tool context", "FAIL", f"Turn 2 didn't call read_file: {calls2}"
        args2 = json.loads(calls2[0]["function"]["arguments"])
        if "TodoList.jsx" in args2.get("path", ""):
            return "Multi-turn tool context", "PASS", f"Correctly used prior tool result: read_file({args2})"
        return "Multi-turn tool context", "FAIL", f"read_file called with wrong/unrelated path: {args2}"
    except Exception as e:
        return "Multi-turn tool context", "FAIL", f"{type(e).__name__}: {e}"


def test_no_hallucinated_tool_call(base_url, api_key, model):
    try:
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "What does the acronym API stand for?"}],
            tools=TOOLS, tool_choice="auto", max_tokens=300,
        )
        calls = get_tool_calls(resp)
        content = get_content(resp)
        if calls:
            return "No hallucinated tool calls", "FAIL", f"Tool called when none was needed: {calls}"
        if content and "application programming interface" in content.lower():
            return "No hallucinated tool calls", "PASS", f"Plain-text answer: {content[:80]!r}"
        return "No hallucinated tool calls", "WARN", f"No tool call (good) but answer looks off: {content!r}"
    except Exception as e:
        return "No hallucinated tool calls", "FAIL", f"{type(e).__name__}: {e}"


def test_streaming_tool_call(base_url, api_key, model):
    try:
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": "Read the contents of README.md"}],
            tools=TOOLS, tool_choice="auto", max_tokens=400, stream=True,
        )
        calls = get_tool_calls(resp)
        if len(calls) != 1:
            return "Streaming reconstruction", "FAIL", f"Expected 1 reconstructed tool call, got {len(calls)}"
        fn = calls[0]["function"]
        if fn["name"] != "read_file":
            return "Streaming reconstruction", "FAIL", f"Expected read_file, got {fn['name']!r}"
        try:
            args = json.loads(fn["arguments"])
        except json.JSONDecodeError as e:
            return "Streaming reconstruction", "FAIL", f"Reconstructed arguments not valid JSON: {fn['arguments']!r} ({e})"
        return "Streaming reconstruction", "PASS", f"read_file({args}) reassembled correctly from stream"
    except Exception as e:
        return "Streaming reconstruction", "FAIL", f"{type(e).__name__}: {e}"


def make_solid_png(width, height, rgb):
    """Build a solid-color 8-bit RGB PNG with the standard library only."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width  # filter type 0 (None) + pixels
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


VISION_OTHER_COLORS = ("green", "blue", "yellow", "black", "white", "orange",
                       "purple", "pink", "gray", "grey", "brown")
VISION_REJECT_HINTS = ("image", "vision", "multimodal", "multi-modal", "multi_modal")


def test_vision(base_url, api_key, model):
    try:
        png = make_solid_png(64, 64, (255, 0, 0))
        data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "What single color fills this image? Answer with one word."},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            max_tokens=1024,  # reasoning tokens come first
        )
        content = get_content(resp) or ""
        finish_reason = resp.get("choices", [{}])[0].get("finish_reason")
        lowered = content.lower()
        has_red = re.search(r"\bred\b", lowered) is not None
        other = [c for c in VISION_OTHER_COLORS if re.search(rf"\b{c}\b", lowered)]
        if has_red and not other:
            return "Vision", "PASS", f"Identified the 64x64 red PNG: {content.strip()[:60]!r}"
        if has_red:
            return "Vision", "FAIL", (f"Answer names red but also {other}: ambiguous, "
                                      f"content={content[:80]!r}, finish_reason={finish_reason}")
        return "Vision", "FAIL", f"Expected 'red', got content={content[:80]!r}, finish_reason={finish_reason}"
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        # 401/403 are auth problems, not a statement about image support.
        if 400 <= e.code < 500 and e.code not in (401, 403):
            return ("Vision", "WARN",
                    f"Model/endpoint does not accept images (HTTP {e.code}): {body[:160]!r}")
        if any(h in body.lower() for h in VISION_REJECT_HINTS):
            return ("Vision", "WARN",
                    f"Model/endpoint does not accept images (HTTP {e.code}): {body[:160]!r}")
        return "Vision", "FAIL", f"HTTPError {e.code}: {body[:160]!r}"
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if any(h in str(e).lower() for h in VISION_REJECT_HINTS):
            return "Vision", "WARN", f"Model/endpoint does not accept images ({msg[:160]})"
        return "Vision", "FAIL", msg


def test_decode_throughput(base_url, api_key, model):
    """Informational only: PASS whenever any tokens were generated. The token
    count includes reasoning tokens, so it often stops at the max_tokens cap."""
    try:
        start = time.time()
        resp = chat_completion(
            base_url, api_key, model,
            messages=[{"role": "user", "content":
                       "Write a ~400-word technical explanation of how a hash map handles collisions."}],
            max_tokens=1024,
        )
        elapsed = time.time() - start
        tokens = (resp.get("usage") or {}).get("completion_tokens") or 0
        finish_reason = resp.get("choices", [{}])[0].get("finish_reason")
        if tokens > 0:
            return ("Decode throughput", "PASS",
                    f"completion_tokens={tokens} (incl. reasoning), finish_reason={finish_reason}, "
                    f"elapsed={elapsed:.1f}s, ~{tokens / elapsed:.1f} tok/s (includes prefill/TTFT)")
        return "Decode throughput", "FAIL", f"No completion_tokens in usage: {resp.get('usage')}"
    except Exception as e:
        return "Decode throughput", "FAIL", f"{type(e).__name__}: {e}"


# =============================================================================
# Runner
# =============================================================================

ALL_TESTS = [
    test_connectivity,
    test_reasoning_present,
    test_small_budget_reasoning_risk,
    test_single_tool_call,
    test_tool_selection_breadth,
    test_multiturn_tool_context,
    test_no_hallucinated_tool_call,
    test_streaming_tool_call,
    test_vision,
    test_decode_throughput,
]


def load_api_key_from_env_file(project_dir):
    env_path = Path(project_dir) / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("LITELLM_MASTER_KEY="):
            value = line.split("=", 1)[1]
            value = value.split("#", 1)[0]  # strip inline comment
            return value.strip()
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.environ.get("LITELLM_MASTER_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", help="Optional path to save a JSON report")
    parser.add_argument("--skip-vision", action="store_true",
                        help="Skip the Vision test (for text-only models/endpoints)")
    args = parser.parse_args()

    api_key = args.api_key or load_api_key_from_env_file(Path(__file__).resolve().parent.parent)
    if not api_key:
        print("ERROR: no API key found. Pass --api-key, set LITELLM_MASTER_KEY, "
              "or run this from a checkout with a populated .env file.", file=sys.stderr)
        sys.exit(1)

    print(f"Testing model={args.model!r} via {args.base_url}\n")

    results = []
    tests = [t for t in ALL_TESTS if not (args.skip_vision and t is test_vision)]
    if args.skip_vision:
        print("(Vision test skipped: --skip-vision)\n")
    for test_fn in tests:
        start = time.time()
        name, status, detail = test_fn(args.base_url, api_key, args.model)
        elapsed = time.time() - start
        marker = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}[status]
        print(f"{marker} {name} ({elapsed:.1f}s)\n      {detail}\n")
        results.append({"name": name, "status": status, "detail": detail, "elapsed_s": round(elapsed, 2)})

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    print(f"{'='*70}\nSummary: {passed} passed, {failed} failed, {warned} warned (of {len(results)})")

    if args.output:
        report = {
            "model": args.model,
            "base_url": args.base_url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "results": results,
            "summary": {"passed": passed, "failed": failed, "warned": warned},
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(f"Report saved to {args.output}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
