#!/usr/bin/env python3
"""
Agentic Task Evaluation — real repository tasks with harness-style tools
=======================================================================
Gives a served model (through agentgateway, OpenAI-compatible tool calling) a
small repository and a real task — fix a bug from a report, add a feature,
make slow code fast, fix a race condition, implement a module from its spec —
plus deterministic tools, and lets it work until it calls `finish`. Hidden
tests the model never sees then score the result.

Tools (no shell / terminal access):
  list_files    files in the workspace with line counts
  read_file     a file with line numbers (offset/limit)
  outline       classes/functions/methods of a Python file with signatures and
                docstring summaries (parsed with `ast`, never executed)
  grep          regex search across the workspace
  write_file    create/overwrite a file
  edit_file     replace an exact, unique snippet in a file
  check_syntax  parse Python files and report syntax errors (no execution)
  run_tests     run pytest on the workspace (optionally one file / node id /
                -k expression) in a throwaway sandbox container
  finish        declare the task done, with a summary

File tools act on a per-task copy of the repository on the host and are
confined to it. The only code execution is run_tests and the final grading,
both in `eval-sandbox:py312` (scripts/eval-tasks/sandbox/Dockerfile, built on
first use) with --network none, a read-only root, tmpfs work dirs, 1 GiB
memory, 2 CPUs, 256 pids, all capabilities dropped and no-new-privileges. The
workspace is streamed in as a tar, so nothing the tests do reaches the host.

Tasks live in scripts/eval-tasks/<id>/: TASK.md (the prompt), workspace/ (the
starting repository), hidden_tests/ (grading), reference/ (a known-good
solution overlaid on workspace/ for --self-test; never shown to the model).

Output: one JSON document (rewritten after every task; meta.complete is false
until the end) with per-turn transcripts, tool calls, token usage, timings,
the final diff and visible + hidden test results; plus each task's final
workspace under <output dir>/<run name>/<task id>/.

Usage:
    python3 scripts/eval-agentic-tasks.py [--only ID[,ID...]] [--model MODEL] [--base-url URL]
                                          [--max-turns N] [--task-minutes N] [--turn-max-tokens N]
                                          [--output FILE] [--resume FILE]
    python3 scripts/eval-agentic-tasks.py --self-test      # check every task's hidden tests: baseline fails, reference passes
    python3 scripts/eval-agentic-tasks.py --list
"""

import argparse
import ast
import difflib
import fnmatch
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE_URL = "http://localhost:4100/v1"   # agentgateway
DEFAULT_MODEL = "qwen3.8-flash-next"
SANDBOX_IMAGE = "eval-sandbox:py312"
REQUEST_TIMEOUT = 1500       # agentgateway's LLM route timeout
TOOL_OUTPUT_LIMIT = 12000    # characters returned to the model per tool call
RECORD_OUTPUT_LIMIT = 4000   # characters of each tool result kept in the transcript
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git"}

PROJECT_DIR = Path(__file__).resolve().parent.parent
TASKS_DIR = Path(__file__).resolve().parent / "eval-tasks"

SYSTEM_PROMPT = """You are an autonomous senior software engineer. You are working alone on a task in a \
Python repository; nobody will answer questions, so make reasonable decisions and keep going.

You have tools to inspect and change the repository and to run its tests. There is no shell. \
Paths are relative to the repository root. Python 3.12 with pytest is available to run_tests.

Work like a professional:
1. Read the task carefully and inspect the relevant code (outline and read_file are faster than reading everything).
2. Make focused, correct changes with edit_file (exact unique snippets) or write_file.
3. Add or update tests for what you changed, run the tests, and fix failures.
4. When the task is fully done and verified, call finish with a short summary. Do not stop before that."""

TOOLS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files under a directory of the repository (recursive), with line counts.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory relative to the repository root (default: root)."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "First line to show, 1-based (default 1)."},
            "limit": {"type": "integer", "description": "Number of lines (default 400)."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "outline",
        "description": "Show the classes, functions and methods of a Python file with line numbers, signatures "
                       "and the first line of each docstring. Parses the file; does not run it.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "grep",
        "description": "Search files for a Python regular expression. Returns path:line: text matches.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "File or directory to search (default: root)."},
            "glob": {"type": "string", "description": "Only files whose relative path matches this glob, e.g. '*.py'."}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content (parent directories are created).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace old_string with new_string in a file. old_string must match exactly (including "
                       "indentation) and be unique unless replace_all is true.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "check_syntax",
        "description": "Parse Python files and report syntax errors without running them.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "A .py file or a directory (default: whole repository)."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Run pytest in a sandbox and return the summary and failure details.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Optional test file, directory or node id, e.g. "
                                                        "'tests/test_x.py::test_name' (default: all tests)."},
            "keyword": {"type": "string", "description": "Optional pytest -k expression."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Call when the task is complete and verified. Ends the session.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string", "description": "What you changed and how you verified it."}},
            "required": ["summary"]}}},
]


def clip(text, limit):
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... [{len(text) - limit} characters omitted] ...\n{text[-half:]}"


# =============================================================================
# Sandbox (pytest only)
# =============================================================================

def ensure_sandbox_image():
    if subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE], capture_output=True).returncode != 0:
        print(f"Building {SANDBOX_IMAGE} ...")
        subprocess.run(["docker", "build", "-q", "-t", SANDBOX_IMAGE, str(TASKS_DIR / "sandbox")], check=True)


def tar_dirs(mapping):
    """Tar {name in archive: host directory} into bytes (files only, no symlinks)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arcname, directory in mapping.items():
            for path in sorted(Path(directory).rglob("*")):
                if path.is_symlink() or not path.is_file() or SKIP_DIRS & set(path.parts):
                    continue
                tar.add(path, arcname=f"{arcname}/{path.relative_to(directory)}", recursive=False)
    return buf.getvalue()


def run_pytest(workspace, pytest_args, grading_dir=None, timeout=300):
    """Run pytest on a copy of `workspace` in the sandbox; return (exit code, output, counts)."""
    mapping = {"ws": workspace}
    if grading_dir:
        mapping["grading"] = grading_dir
    ini = 'printf "[pytest]\\n" > /work/grading/pytest.ini && ' if grading_dir else ""
    script = ('tar -x -C /work && ' + ini + 'cd /work/ws && exec timeout -k 5 "$0" python -m pytest -q '
              '-p no:cacheprovider --tb=short -rfE --timeout=120 "$@"')
    cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "1g", "--memory-swap", "1g",
           "--cpus", "2", "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--read-only", "--tmpfs", "/tmp:rw,exec,size=512m,mode=1777", "--tmpfs", "/work:rw,exec,size=256m,mode=1777",
           SANDBOX_IMAGE, "sh", "-c", script, str(timeout), *pytest_args]
    try:
        proc = subprocess.run(cmd, input=tar_dirs(mapping), capture_output=True, timeout=timeout + 60)
        output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        code = proc.returncode
    except subprocess.TimeoutExpired:
        output, code = f"sandbox did not finish within {timeout + 60}s", 124
    if code == 124:
        output += f"\n[test run timed out after {timeout}s]"
    counts = {}
    summary = [l for l in output.splitlines() if re.search(r"\d+ (passed|failed|errors?|skipped)", l)]
    if summary:
        for n, kind in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)", summary[-1]):
            counts["error" if kind.startswith("error") else kind] = int(n)
    return code, output, counts


def run_hidden_tests(workspace, task_dir):
    code, output, counts = run_pytest(
        workspace, ["--rootdir=/work/grading", "-c", "/work/grading/pytest.ini", "--confcutdir=/work/grading",
                    "/work/grading"], grading_dir=task_dir / "hidden_tests", timeout=600)
    total = sum(counts.get(k, 0) for k in ("passed", "failed", "error"))
    return {"exit_code": code, "passed": counts.get("passed", 0), "failed": counts.get("failed", 0),
            "errors": counts.get("error", 0), "total": total,
            "score": round(counts.get("passed", 0) / total, 3) if total else 0.0,
            "output": clip(output, 20000)}


# =============================================================================
# Deterministic tools (host side, confined to the workspace)
# =============================================================================

class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, path, must_exist=True):
        p = (self.root / (path or ".")).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"path {path!r} is outside the repository")
        if must_exist and not p.exists():
            raise FileNotFoundError(f"{path} does not exist")
        return p

    def rel(self, p):
        return str(p.relative_to(self.root)) or "."

    def files(self, base):
        if base.is_file():
            return [base]
        return [p for p in sorted(base.rglob("*")) if p.is_file() and not SKIP_DIRS & set(p.relative_to(self.root).parts)]

    @staticmethod
    def text(p):
        if p.stat().st_size > 1_000_000:
            raise ValueError(f"{p.name} is larger than 1 MB")
        return p.read_text(errors="replace")

    def list_files(self, path=None):
        base = self.resolve(path)
        lines = []
        for p in self.files(base)[:500]:
            try:
                n = self.text(p).count("\n")
                lines.append(f"{self.rel(p)}  ({n} lines)")
            except ValueError:
                lines.append(f"{self.rel(p)}  (large file)")
        return "\n".join(lines) or "(no files)"

    def read_file(self, path, offset=1, limit=400):
        lines = self.text(self.resolve(path)).splitlines()
        start = max(1, int(offset or 1))
        end = min(len(lines), start + max(1, int(limit or 400)) - 1)
        body = "\n".join(f"{i:>5}\t{lines[i - 1]}" for i in range(start, end + 1))
        if end < len(lines):
            body += f"\n... ({len(lines) - end} more lines; continue with offset={end + 1})"
        return body or "(empty file)"

    def outline(self, path):
        p = self.resolve(path)
        tree = ast.parse(self.text(p), filename=str(p))
        out = []

        def visit(nodes, depth):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if isinstance(node, ast.ClassDef):
                        sig = f"class {node.name}" + (f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else "")
                    else:
                        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
                        sig = f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}({ast.unparse(node.args)}){ret}"
                    doc = (ast.get_docstring(node) or "").strip().splitlines()
                    end = getattr(node, "end_lineno", node.lineno)
                    out.append(f"{'    ' * depth}{sig}   [lines {node.lineno}-{end}]" + (f"  # {doc[0]}" if doc else ""))
                    visit(node.body, depth + 1)
        visit(tree.body, 0)
        module_doc = (ast.get_docstring(tree) or "").strip().splitlines()
        head = f"module docstring: {module_doc[0]}\n" if module_doc else ""
        return head + ("\n".join(out) or "(no classes or functions)")

    def grep(self, pattern, path=None, glob=None):
        rx = re.compile(pattern)
        hits = []
        for p in self.files(self.resolve(path)):
            rel = self.rel(p)
            if glob and not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(p.name, glob)):
                continue
            try:
                text = self.text(p)
            except ValueError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line}")
                    if len(hits) >= 300:
                        return "\n".join(hits) + "\n... (stopped at 300 matches)"
        return "\n".join(hits) or "(no matches)"

    def write_file(self, path, content):
        if len(content) > 300_000:
            raise ValueError("content larger than 300 KB")
        p = self.resolve(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {self.rel(p)} ({content.count(chr(10)) + (not content.endswith(chr(10)) and bool(content))} lines)"

    def edit_file(self, path, old_string, new_string, replace_all=False):
        p = self.resolve(path)
        text = self.text(p)
        n = text.count(old_string) if old_string else 0
        if n == 0:
            raise ValueError("old_string not found (it must match exactly, including whitespace); read the file again")
        if n > 1 and not replace_all:
            raise ValueError(f"old_string occurs {n} times; add surrounding lines to make it unique or set replace_all")
        p.write_text(text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1))
        return f"edited {self.rel(p)} ({n if replace_all else 1} replacement{'s' if replace_all and n > 1 else ''})"

    def check_syntax(self, path=None):
        problems, checked = [], 0
        for p in self.files(self.resolve(path)):
            if p.suffix != ".py":
                continue
            checked += 1
            try:
                ast.parse(self.text(p), filename=self.rel(p))
            except SyntaxError as e:
                problems.append(f"{self.rel(p)}:{e.lineno}:{e.offset}: {e.msg}\n    {(e.text or '').rstrip()}")
        return "\n".join(problems) if problems else f"OK: {checked} Python file(s) parse without errors"

    def run_tests(self, target=None, keyword=None):
        args = []
        if target:
            file_part = target.split("::", 1)[0]
            if target.startswith("-"):
                raise ValueError("target must be a path or node id")
            self.resolve(file_part)
            args.append(target)
        if keyword:
            if keyword.startswith("-"):
                raise ValueError("keyword must be a -k expression")
            args += ["-k", keyword]
        start = time.time()
        code, output, _counts = run_pytest(self.root, args)
        return f"[pytest exit code {code}, {time.time() - start:.1f}s]\n{output}"


def call_tool(ws, name, args):
    """Run one tool; returns (output text, ok)."""
    handlers = {"list_files": ws.list_files, "read_file": ws.read_file, "outline": ws.outline, "grep": ws.grep,
                "write_file": ws.write_file, "edit_file": ws.edit_file, "check_syntax": ws.check_syntax,
                "run_tests": ws.run_tests}
    if name not in handlers:
        return f"ERROR: unknown tool {name!r}", False
    try:
        return handlers[name](**args), True
    except TypeError as e:
        return f"ERROR: bad arguments for {name}: {e}", False
    except (ValueError, OSError, SyntaxError, re.error) as e:
        return f"ERROR: {e}", False


# =============================================================================
# Model loop
# =============================================================================

def chat(args, api_key, messages, max_tokens):
    payload = {"model": args.model, "messages": messages, "tools": TOOLS, "tool_choice": "auto",
               "max_tokens": max_tokens}
    req = urllib.request.Request(f"{args.base_url}/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_text(errors="replace")
            for p in sorted(Path(directory).rglob("*")) if p.is_file() and not SKIP_DIRS & set(p.parts)}


def unified_diff(before, after):
    chunks = []
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name), after.get(name)
        if a == b:
            continue
        chunks.extend(difflib.unified_diff((a or "").splitlines(True), (b or "").splitlines(True),
                                           f"a/{name}" if a is not None else "/dev/null",
                                           f"b/{name}" if b is not None else "/dev/null"))
    return "".join(chunks)


def run_task(task_dir, run_dir, args, api_key):
    task_id = task_dir.name
    work = run_dir / task_id / "workspace"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(task_dir / "workspace", work)
    ws = Workspace(work)
    baseline = snapshot(work)
    task_text = (task_dir / "TASK.md").read_text()

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{task_text}\n\nRepository files:\n{ws.list_files()}"}]
    record = {"id": task_id, "task": task_text, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "status": None, "finish_summary": None, "turns": [], "tool_counts": {},
              "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "error": None}
    start = time.time()
    nudged = False
    print(f"\n=== {task_id} ===")
    try:
        for turn in range(1, args.max_turns + 1):
            if time.time() - start > args.task_minutes * 60:
                record["status"] = "time_limit"
                break
            t0 = time.time()
            resp = chat(args, api_key, messages, args.turn_max_tokens)
            choice = resp["choices"][0]
            msg = choice["message"]
            usage = resp.get("usage") or {}
            for k in ("prompt_tokens", "completion_tokens"):
                record["usage"][k] += usage.get(k, 0)
            tool_calls = msg.get("tool_calls") or []
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            turn_rec = {"turn": turn, "seconds": round(time.time() - t0, 1), "finish_reason": choice.get("finish_reason"),
                        "usage": usage, "reasoning_chars": len(reasoning), "reasoning": clip(reasoning, 6000),
                        "content": msg.get("content"), "tool_calls": []}
            record["turns"].append(turn_rec)
            assistant = {"role": "assistant", "content": msg.get("content") or ""}
            if tool_calls:
                assistant["tool_calls"] = [{"id": tc["id"], "type": "function", "function": tc["function"]}
                                           for tc in tool_calls]
            messages.append(assistant)
            names = []
            finished = False
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    targs = json.loads(tc["function"].get("arguments") or "{}")
                    if not isinstance(targs, dict):
                        raise ValueError("arguments must be a JSON object")
                except ValueError as e:
                    output, ok = f"ERROR: arguments are not valid JSON: {e}", False
                    targs = {}
                else:
                    if name == "finish":
                        output, ok, finished = "Session finished.", True, True
                        record["finish_summary"] = targs.get("summary")
                    else:
                        output, ok = call_tool(ws, name, targs)
                record["tool_counts"][name] = record["tool_counts"].get(name, 0) + 1
                names.append(name if ok else f"{name}!")
                shown_args = {k: (clip(v, 600) if isinstance(v, str) else v) for k, v in targs.items()}
                turn_rec["tool_calls"].append({"name": name, "args": shown_args, "ok": ok,
                                               "result": clip(output, RECORD_OUTPUT_LIMIT)})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": clip(output, TOOL_OUTPUT_LIMIT)})
            print(f"  turn {turn:>2}  {turn_rec['seconds']:>6.1f}s  out={usage.get('completion_tokens', '?'):>6}  "
                  f"{choice.get('finish_reason'):<10} {', '.join(names) or '(no tool call)'}")
            if finished:
                record["status"] = "finished"
                break
            if not tool_calls:
                if choice.get("finish_reason") == "length":
                    messages.append({"role": "user", "content": "Your reply was cut off by the token limit. Think more "
                                     "briefly and continue the task using the tools."})
                elif not nudged:
                    nudged = True
                    messages.append({"role": "user", "content": "Continue working with the tools. If the task is "
                                     "complete and verified, call finish."})
                else:
                    record["status"] = "stopped_without_finish"
                    break
            if record["usage"]["completion_tokens"] > args.task_max_tokens:
                record["status"] = "token_limit"
                break
        else:
            record["status"] = "turn_limit"
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        detail = e.read().decode("utf-8", "replace")[:500] if isinstance(e, urllib.error.HTTPError) else ""
        record["status"] = "error"
        record["error"] = f"{type(e).__name__}: {e} {detail}".strip()

    record["seconds"] = round(time.time() - start, 1)
    record["diff"] = clip(unified_diff(baseline, snapshot(work)), 60000)
    code, output, counts = run_pytest(work, [])
    record["visible_tests"] = {"exit_code": code, **counts, "output": clip(output, 8000)}
    record["hidden_tests"] = run_hidden_tests(work, task_dir)
    record["workspace_dir"] = str(work)
    h = record["hidden_tests"]
    print(f"  -> {record['status']}, {len(record['turns'])} turns, {record['seconds']:.0f}s, "
          f"{record['usage']['completion_tokens']} output tokens; hidden tests {h['passed']}/{h['total']}")
    return record


# =============================================================================
# Entry points
# =============================================================================

def all_tasks():
    return sorted(p for p in TASKS_DIR.iterdir() if (p / "TASK.md").exists())


def self_test(tasks):
    """Hidden tests must fail on the starting workspace and pass on the reference solution."""
    ok = True
    for task_dir in tasks:
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"eval-selftest-{task_dir.name}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(task_dir / "workspace", tmp)
        base = run_hidden_tests(tmp, task_dir)
        shutil.copytree(task_dir / "reference", tmp, dirs_exist_ok=True)
        ref = run_hidden_tests(tmp, task_dir)
        _code, _out, visible = run_pytest(tmp, [])
        shutil.rmtree(tmp, ignore_errors=True)
        good = base["passed"] < base["total"] and ref["passed"] == ref["total"] > 0
        ok &= good
        print(f"{'OK  ' if good else 'FAIL'} {task_dir.name:<34} baseline {base['passed']}/{base['total']}  "
              f"reference {ref['passed']}/{ref['total']}  (visible tests on reference: {visible})")
        if not good:
            print(ref["output"][-3000:])
    return ok


def load_api_key():
    key = os.environ.get("LITELLM_MASTER_KEY")
    env_path = PROJECT_DIR / ".env"
    if not key and env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("LITELLM_MASTER_KEY="):
                key = line.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--only", help="Comma-separated task ids")
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--task-minutes", type=float, default=30, help="Wall-clock limit per task (checked between turns)")
    parser.add_argument("--turn-max-tokens", type=int, default=16384, help="max_tokens per model turn (reasoning included)")
    parser.add_argument("--task-max-tokens", type=int, default=150_000, help="Output-token budget per task")
    parser.add_argument("--output", help="JSON path (default ai-workspace/reports/agentic-eval-<model>-<UTC>.json)")
    parser.add_argument("--resume", metavar="FILE", help="Continue an earlier run: skip tasks it already recorded "
                                                          "(except status 'error'), save into the same file")
    parser.add_argument("--self-test", action="store_true", help="Validate the tasks (no model calls)")
    parser.add_argument("--list", action="store_true", help="List the tasks and exit")
    args = parser.parse_args()
    if args.resume and args.output:
        parser.error("--resume saves into FILE; don't combine it with --output")

    tasks = all_tasks()
    if args.only:
        wanted = {t.strip() for t in args.only.split(",")}
        unknown = wanted - {t.name for t in tasks}
        if unknown:
            sys.exit(f"ERROR: unknown task id(s): {', '.join(sorted(unknown))}")
        tasks = [t for t in tasks if t.name in wanted]
    if args.list:
        for t in tasks:
            print(f"{t.name:<34} {(t / 'TASK.md').read_text().splitlines()[0].lstrip('# ')}")
        return

    ensure_sandbox_image()
    if args.self_test:
        sys.exit(0 if self_test(tasks) else 1)

    api_key = load_api_key()
    if not api_key:
        sys.exit("ERROR: no API key. Set LITELLM_MASTER_KEY or populate .env.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.resume or args.output or
                  PROJECT_DIR / "ai-workspace" / "reports" / f"agentic-eval-{args.model}-{stamp}.json")
    records = []
    if args.resume:
        previous = json.loads(output.read_text())
        if previous["meta"]["model"] != args.model:
            sys.exit(f"ERROR: {output} is for model {previous['meta']['model']!r}, not {args.model!r}")
        records = [r for r in previous["results"] if r["status"] != "error"]
        done = {r["id"] for r in records}
        tasks = [t for t in tasks if t.name not in done]
        print(f"Resuming {output}: keeping {len(records)}, running {len(tasks)}")
    run_dir = output.with_suffix("")   # final workspaces live next to the JSON

    def save(complete):
        hidden = [r["hidden_tests"] for r in records]
        doc = {"meta": {
            "model": args.model, "base_url": args.base_url, "complete": complete,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "limits": {"max_turns": args.max_turns, "task_minutes": args.task_minutes,
                       "turn_max_tokens": args.turn_max_tokens, "task_max_tokens": args.task_max_tokens},
            "system_prompt": SYSTEM_PROMPT, "tools": [t["function"]["name"] for t in TOOLS],
            "tasks": len(records),
            "finished": sum(r["status"] == "finished" for r in records),
            "hidden_tests_passed": sum(h["passed"] for h in hidden),
            "hidden_tests_total": sum(h["total"] for h in hidden),
            "tasks_fully_passing": sum(h["total"] > 0 and h["passed"] == h["total"] for h in hidden),
            "completion_tokens": sum(r["usage"]["completion_tokens"] for r in records),
            "seconds": round(sum(r.get("seconds", 0) for r in records), 1),
            "grading": None,
        }, "results": records}
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, output)
        return doc["meta"]

    print(f"Agentic eval: model={args.model!r} via {args.base_url}, {len(tasks)} task(s); saving to {output}")
    for task_dir in tasks:
        records.append(run_task(task_dir, run_dir, args, api_key))
        save(complete=False)
    m = save(complete=True)
    print(f"\n{m['tasks']} tasks, {m['finished']} finished, {m['tasks_fully_passing']} fully passing hidden tests "
          f"({m['hidden_tests_passed']}/{m['hidden_tests_total']}), {m['completion_tokens']} output tokens, {m['seconds']}s")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
