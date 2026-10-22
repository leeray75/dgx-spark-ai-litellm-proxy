#!/usr/bin/env python3
"""
Agentic Capability Test (LangGraph) — Thinking, Reasoning, and Tool Calling
============================================================================
Same goal as test-agentic-capabilities.py, but drives the model through a
REAL agentic loop (langgraph.prebuilt.create_react_agent) instead of manual
message reconstruction. This means tool calls actually execute against
synthetic tool implementations and their results are automatically fed back
into the next model turn by LangGraph's own runtime — the same mechanism an
agent harness like opencode or Cline relies on, not a simulation of it.

Requires (already installed into ../.venv by this session):
    pip install langgraph langchain-openai

Covers:
  1. Connectivity            - basic non-tool completion through ChatOpenAI
  2. Reasoning presence       - thinking pass fires and reaches a correct answer
  3. Single tool call         - one unambiguous prompt, one correct tool, and
                                the agent's FINAL answer actually reflects the
                                tool's (synthetic) return value
  4. Tool selection breadth   - one prompt per tool in the palette
  5. Real multi-step chaining - a task needing two sequential tool calls,
                                run through the ACTUAL agent loop (no manual
                                message injection) — the strongest test that
                                a Cline/opencode-style session would work
  6. No hallucinated calls    - a prompt with no matching tool must NOT invent one

Usage:
    .venv/bin/python3 scripts/test-agentic-capabilities-langgraph.py [--base-url URL] [--api-key KEY]
                                                                      [--model MODEL] [--output FILE]
                                                                      [--max-tokens N]

Examples:
    # default: LiteLLM at http://localhost:4000/v1, key from LITELLM_MASTER_KEY or .env
    # default model: qwen3.8-flash-next (Flash-Next, the default stack since 2026-10-22)
    .venv/bin/python3 scripts/test-agentic-capabilities-langgraph.py
    # Qwen3.8-27B (ROLLBACK stack; restore the ROLLBACK blocks in litellm-config.yaml first):
    .venv/bin/python3 scripts/test-agentic-capabilities-langgraph.py --model qwen3.8-27b
    # ...or directly against the engine (vLLM has no --api-key, any token works):
    .venv/bin/python3 scripts/test-agentic-capabilities-langgraph.py --base-url http://localhost:8301/v1 --model qwen3.8-flash-next
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

DEFAULT_BASE_URL = "http://localhost:4000/v1"
DEFAULT_MODEL = "qwen3.8-flash-next"
RECURSION_LIMIT = 15


# =============================================================================
# Synthetic tools — deterministic fake implementations of a small, internally
# CONSISTENT fake codebase. The point isn't real file I/O, it's verifying the
# MODEL picks the right tool with correct arguments and that LangGraph's real
# loop carries a tool's return value into the next turn correctly.
#
# IMPORTANT: every result below is deliberately realistic and cross-consistent
# (a search match's file/line/snippet always matches what read_file returns
# for that same path, and what execute_command's grep/find output shows). An
# earlier version of this script returned generic placeholders like
# '"# match for {query}"' or '"(synthetic output)"' — a careful model has good
# reason to distrust a result that looks like a canned stub rather than real
# code, and that's exactly what triggered a 28-step retry spiral in testing
# (the model correctly noticing the tool output didn't look real, not the
# model "overthinking" a clean task). Keep every new fixture below equally
# realistic and internally consistent, or this confound comes back.
# =============================================================================

_FAKE_FILES = {
    "src/components/TodoList.jsx": (
        "import React, { Component } from 'react';\n\n"
        "export class TodoList extends Component {\n"
        "  render() {\n"
        "    return <ul>{this.props.items.map(i => <li key={i.id}>{i.text}</li>)}</ul>;\n"
        "  }\n"
        "}\n"
    ),
    "src/components/LoginForm.jsx": (
        "import React, { useState } from 'react';\n\n"
        "export function LoginForm({ onLogin }) {\n"
        "  const [email, setEmail] = useState('');\n"
        "  const [password, setPassword] = useState('');\n\n"
        "  const handleSubmit = (e) => {\n"
        "    e.preventDefault();\n"
        "    onLogin({ email, password });\n"
        "  };\n\n"
        "  return (\n"
        "    <form onSubmit={handleSubmit}>\n"
        "      <input value={email} onChange={e => setEmail(e.target.value)} />\n"
        "      <input type=\"password\" value={password} onChange={e => setPassword(e.target.value)} />\n"
        "      <button type=\"submit\">Log in</button>\n"
        "    </form>\n"
        "  );\n"
        "}\n"
    ),
    "package.json": json.dumps({"name": "demo-app", "version": "1.0.0", "scripts": {"test": "jest"}}, indent=2),
    "src/app.py": (
        "from flask import Flask\n\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'Hello, world!'\n\n"
        "if __name__ == '__main__':\n"
        "    app.run(port=5000)\n"
    ),
}


@tool
def search_code(query: str, path: str = "") -> str:
    """Search the codebase for a symbol, function, or text pattern."""
    q = query.lower()
    if "todolist" in q:
        return json.dumps({"matches": [
            {"file": "src/components/TodoList.jsx", "line": 3,
             "snippet": "export class TodoList extends Component {"},
        ]})
    if "handlesubmit" in q or "submit" in q:
        return json.dumps({"matches": [
            {"file": "src/components/LoginForm.jsx", "line": 8,
             "snippet": "  const handleSubmit = (e) => {"},
            {"file": "src/components/LoginForm.jsx", "line": 15,
             "snippet": "    <form onSubmit={handleSubmit}>"},
        ]})
    return json.dumps({"matches": [], "note": f"No matches found for {query!r}."})


@tool
def read_file(path: str) -> str:
    """Read the contents of a file at the given path."""
    for known_path, content in _FAKE_FILES.items():
        if known_path in path or path in known_path:
            return content
    return f"cat: {path}: No such file or directory"


@tool
def write_file(path: str, content: str) -> str:
    """Create a NEW file, or overwrite an EXISTING file, with the given full
    content. This is the correct tool any time the task is to create or
    rewrite a file. Do not use execute_command with shell redirection
    (echo/cat/heredoc) for file creation or edits — use this tool instead."""
    return f"Wrote {len(content)} bytes to {path}"


@tool
def execute_command(command: str) -> str:
    """Run a shell command — for things like running tests, builds, git
    operations, or search utilities (grep/find/ls). Do NOT use this to
    create or edit files; use write_file or read_file for file operations."""
    c = command.lower()

    # Order matters: check the most specific patterns first.
    if "grep" in c and ("handlesubmit" in c or "submit" in c):
        return ("src/components/LoginForm.jsx:8:  const handleSubmit = (e) => {\n"
                "src/components/LoginForm.jsx:15:    <form onSubmit={handleSubmit}>")
    if "grep" in c:
        return ""  # realistic: grep with no matches produces no output, not an error

    if "cat " in c:
        for known_path, content in _FAKE_FILES.items():
            if known_path.split("/")[-1] in c or known_path in c:
                return content

    if "npm test" in c or "jest" in c or ("test" in c and "npm" in c):
        return "PASS  12 tests, 0 failures"

    if any(v in c for v in ("--version", "node -v", "npm -v")):
        if "node" in c:
            return "v22.11.0"
        if "npm" in c:
            return "10.9.0"
        return "v22.11.0"
    if c.startswith("which ") or " which " in c:
        if "node" in c:
            return "/usr/local/bin/node"
        if "npm" in c:
            return "/usr/local/bin/npm"
        return "/usr/local/bin/" + command.split()[-1]

    if c.strip() == "pwd" or c.startswith("pwd"):
        return "/home/user/demo-app"

    if any(v in c for v in ("ls", "find", "tree", "dir")):
        return "\n".join(sorted(_FAKE_FILES.keys()))

    return "(command completed with no output)"


TOOLS = [search_code, read_file, write_file, execute_command]


# =============================================================================
# Helpers
# =============================================================================

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


def extract_tool_calls(messages):
    """Every tool call any AIMessage in the transcript made, in order."""
    calls = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                calls.append({"name": tc["name"], "args": tc["args"]})
    return calls


def extract_reasoning(messages):
    """Check additional_kwargs / response_metadata for a reasoning field,
    wherever langchain-openai surfaced it from the raw API response."""
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        for source in (m.additional_kwargs, getattr(m, "response_metadata", {}) or {}):
            for key in ("reasoning_content", "reasoning"):
                if source.get(key):
                    return source[key]
    return None


def final_answer(messages):
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.content:
            return m.content
    return None


def run_agent(agent, prompt):
    result = agent.invoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    return result["messages"]


# =============================================================================
# Tests
# =============================================================================

def test_connectivity(agent):
    try:
        messages = run_agent(agent, "Reply with exactly: pong")
        answer = final_answer(messages)
        if answer and "pong" in answer.lower():
            return "Connectivity", "PASS", f"Got: {answer!r}"
        return "Connectivity", "WARN", f"Unexpected: {answer!r}"
    except Exception as e:
        return "Connectivity", "FAIL", f"{type(e).__name__}: {e}"


def test_reasoning_present(agent):
    try:
        messages = run_agent(agent, "What is 17 * 24? Think it through, then give just the final number on the last line.")
        reasoning = extract_reasoning(messages)
        answer = final_answer(messages) or ""
        correct = "408" in answer
        if reasoning:
            return "Reasoning presence", ("PASS" if correct else "WARN"), \
                f"reasoning captured ({len(reasoning)} chars), correct_answer={correct}, answer_tail={answer[-60:]!r}"
        return "Reasoning presence", "WARN", \
            f"No reasoning field surfaced via langchain_openai (correct_answer={correct}) — " \
            "may be a langchain_openai field-mapping gap rather than thinking actually being off; " \
            "cross-check with the raw-HTTP script's usage.completion_tokens_details.reasoning_tokens."
    except Exception as e:
        return "Reasoning presence", "FAIL", f"{type(e).__name__}: {e}"


def test_single_tool_call(agent):
    try:
        messages = run_agent(agent, "Read the contents of the file src/app.py, then tell me what it does in one sentence.")
        calls = extract_tool_calls(messages)
        if not calls or calls[0]["name"] != "read_file":
            return "Single tool call", "FAIL", f"Expected read_file first, got: {calls}"
        answer = final_answer(messages) or ""
        if "flask" in answer.lower() or "hello" in answer.lower():
            return "Single tool call", "PASS", f"call={calls[0]}, final answer reflects tool result: {answer[:80]!r}"
        return "Single tool call", "WARN", f"Tool called correctly ({calls[0]}) but final answer doesn't clearly use its result: {answer[:80]!r}"
    except Exception as e:
        return "Single tool call", "FAIL", f"{type(e).__name__}: {e}"


TOOL_SELECTION_CASES = [
    ("Find every place the function `handleSubmit` is called in the codebase", "search_code"),
    ("Show me what's in package.json", "read_file"),
    ("Create a new file called utils/helpers.js with an empty export default {}", "write_file"),
    ("Run the test suite with npm test", "execute_command"),
]


def test_tool_selection_breadth(agent):
    results = []
    for prompt, expected in TOOL_SELECTION_CASES:
        try:
            messages = run_agent(agent, prompt)
            calls = extract_tool_calls(messages)
            got = calls[0]["name"] if calls else None
            results.append((prompt, "PASS" if got == expected else "FAIL", got or "no call"))
        except Exception as e:
            results.append((prompt, "FAIL", f"{type(e).__name__}: {e}"))
    failures = [r for r in results if r[1] == "FAIL"]
    status = "PASS" if not failures else "FAIL"
    detail = "; ".join(f"[{s}] {p[:40]}... -> {d}" for p, s, d in results)
    return f"Tool selection breadth ({len(results)-len(failures)}/{len(results)})", status, detail


def test_real_multistep_chain(agent):
    """No manual message injection — let LangGraph's own loop decide to call
    search_code, receive the synthetic result, then decide to call read_file
    with the path THAT RESULT contained. This is the real test."""
    try:
        messages = run_agent(agent, "Find where the class TodoList is defined, then read that entire file and summarize it.")
        calls = extract_tool_calls(messages)
        names = [c["name"] for c in calls]
        if "search_code" not in names:
            return "Real multi-step chain", "FAIL", f"Never called search_code: {calls}"
        if "read_file" not in names:
            return "Real multi-step chain", "FAIL", f"Never followed up with read_file: {calls}"
        read_call = next(c for c in calls if c["name"] == "read_file")
        if "TodoList" not in read_call["args"].get("path", ""):
            return "Real multi-step chain", "FAIL", \
                f"read_file called but with the wrong path (didn't use search_code's result): {read_call}"
        answer = final_answer(messages) or ""
        if "Component" in answer or "render" in answer.lower():
            return "Real multi-step chain", "PASS", f"calls={names}, final answer reflects the file content"
        return "Real multi-step chain", "WARN", f"Chain worked ({names}) but final summary looks generic: {answer[:100]!r}"
    except Exception as e:
        return "Real multi-step chain", "FAIL", f"{type(e).__name__}: {e}"


def test_no_hallucinated_tool_call(agent):
    try:
        messages = run_agent(agent, "What does the acronym API stand for?")
        calls = extract_tool_calls(messages)
        answer = final_answer(messages) or ""
        if calls:
            return "No hallucinated tool calls", "FAIL", f"Tool called when none was needed: {calls}"
        if "application programming interface" in answer.lower():
            return "No hallucinated tool calls", "PASS", f"Plain-text answer: {answer[:80]!r}"
        return "No hallucinated tool calls", "WARN", f"No tool called (good) but answer looks off: {answer!r}"
    except Exception as e:
        return "No hallucinated tool calls", "FAIL", f"{type(e).__name__}: {e}"


ALL_TESTS = [
    test_connectivity,
    test_reasoning_present,
    test_single_tool_call,
    test_tool_selection_breadth,
    test_real_multistep_chain,
    test_no_hallucinated_tool_call,
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.environ.get("LITELLM_MASTER_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", help="Optional path to save a JSON report")
    parser.add_argument("--max-tokens", type=int, default=800)
    args = parser.parse_args()

    api_key = args.api_key or load_api_key_from_env_file(Path(__file__).resolve().parent.parent)
    if not api_key:
        print("ERROR: no API key found. Pass --api-key, set LITELLM_MASTER_KEY, "
              "or run this from a checkout with a populated .env file.", file=sys.stderr)
        sys.exit(1)

    llm = ChatOpenAI(
        model=args.model,
        base_url=args.base_url,
        api_key=api_key,
        max_tokens=args.max_tokens,
        timeout=120,
    )
    agent = create_react_agent(llm, TOOLS)

    print(f"Testing model={args.model!r} via {args.base_url} (LangGraph create_react_agent)\n")

    results = []
    for test_fn in ALL_TESTS:
        start = time.time()
        name, status, detail = test_fn(agent)
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
            "model": args.model, "base_url": args.base_url,
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
