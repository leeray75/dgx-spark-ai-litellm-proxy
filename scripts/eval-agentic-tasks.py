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
  write_file    create/overwrite a file (Python files syntax-checked)
  edit_file     replace an exact, unique snippet; echoes the edited lines and
                a syntax check
  delete_file   remove a file (scratch files)
  show_diff     unified diff of all changes since the start
  check_syntax  parse Python files and report syntax errors (no execution)
  run_tests     run pytest (optionally one file / node id / -k expression,
                show_output for print()) in a throwaway sandbox container;
                summary + failing tests first; a passing full run checkpoints
                the workspace
  run_python    run a short snippet in the same sandbox and show its output
  finish        declare the task done; refused once if files changed since
                the last passing full test run

Every tool result carries "turn N/M"; the last turns add a wrap-up reminder.
Grading runs the hidden tests on the final workspace and, when it differs, on
the last checkpoint (the last passing full run), so a late broken edit is
visible as such.

File tools act on a per-task copy of the repository on the host and are
confined to it. The only code execution is run_tests, run_python and the final grading,
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
                                          [--repeats N] [--max-turns N] [--task-minutes N] [--turn-max-tokens N]
                                          [--compact-at-tokens N] [--keep-recent-turns N]
                                          [--output FILE] [--resume FILE]
    python3 scripts/eval-agentic-tasks.py --repeats 1      # quick single pass (default is 3 attempts per task)

Context: like Goose/OpenCode/Cline, once a turn's prompt passes --compact-at-tokens
(default 48k) the tool outputs and large tool arguments older than the last
--keep-recent-turns (default 8) turns become one-line stubs.

Statistics: each task runs --repeats times (attempt 1 of every task first);
meta.per_task gives pass rate, score mean/min/max/stdev, turns and time.
meta.sampling records the engine's default sampling (the harness sends none,
like the real harnesses). Every attempt also gets mechanical checks: scratch
files left behind, original tests removed, original tests run against the
final code, diff size vs. the reference, first passing turn, tool error rate.
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
2. Make focused, correct changes with edit_file (exact unique snippets) or write_file. Keep the change no larger
   than the task needs; don't gold-plate.
3. Add or update tests for what you changed, run the full test suite, and fix failures. Use run_python to inspect
   values instead of writing throwaway tests, and delete any scratch files you create.
4. Before finishing, review your whole change with show_diff and make sure the last full run_tests passed with no
   edits after it.
5. End the session by calling the finish tool. A plain text reply does not end it.

Every tool result shows the turn budget ("turn N/M"). You have a limited number of turns: once the task works and is
verified, finish rather than polishing."""

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
        "description": "Create or overwrite a file with the given content (parent directories are created). "
                       "Python files are syntax-checked after writing.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace old_string with new_string in a file. old_string must match exactly (including "
                       "indentation) and be unique unless replace_all is true. Returns the edited lines with "
                       "context and, for Python files, a syntax check.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "delete_file",
        "description": "Delete a file (e.g. a scratch file you created).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "show_diff",
        "description": "Unified diff of everything you changed since the task started (optionally one file or "
                       "directory). Use it to review your work before finishing.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "check_syntax",
        "description": "Parse Python files and report syntax errors without running them.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "A .py file or a directory (default: whole repository)."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Run pytest in a sandbox. Returns a summary line, the list of failing tests, then the pytest "
                       "output. A passing run of the full suite (no target/keyword) checkpoints the workspace.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Optional test file, directory or node id, e.g. "
                                                        "'tests/test_x.py::test_name' (default: all tests)."},
            "keyword": {"type": "string", "description": "Optional pytest -k expression."},
            "show_output": {"type": "boolean", "description": "Show print() output from tests (pytest -s)."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Run a short Python snippet in the sandbox with the repository importable (cwd = repository "
                       "root, no network, files written are discarded) and return its stdout/stderr. Use it to "
                       "inspect values or try an API; not a substitute for tests.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"},
            "timeout": {"type": "integer", "description": "Seconds, 1-60 (default 30)."}},
            "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Call when the task is complete and verified. Ends the session. If files changed since the "
                       "last passing full test run, the first call is refused with a warning.",
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


def tar_dirs(mapping, extra_files=None):
    """Tar {name in archive: host directory} (files only, no symlinks) plus {archive path: text} into bytes."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arcname, directory in mapping.items():
            for path in sorted(Path(directory).rglob("*")):
                if path.is_symlink() or not path.is_file() or SKIP_DIRS & set(path.parts):
                    continue
                tar.add(path, arcname=f"{arcname}/{path.relative_to(directory)}", recursive=False)
        for arcname, text in (extra_files or {}).items():
            data = text.encode()
            info = tarfile.TarInfo(arcname)
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sandbox_run(mapping, script, args, timeout, extra_files=None):
    """Unpack the tar into /work and run `sh -c script timeout *args` in a locked-down container."""
    cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "1g", "--memory-swap", "1g",
           "--cpus", "2", "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--read-only", "--tmpfs", "/tmp:rw,exec,size=512m,mode=1777", "--tmpfs", "/work:rw,exec,size=256m,mode=1777",
           SANDBOX_IMAGE, "sh", "-c", "tar -x -C /work && " + script, str(timeout), *args]
    try:
        proc = subprocess.run(cmd, input=tar_dirs(mapping, extra_files), capture_output=True, timeout=timeout + 60)
        output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        code = proc.returncode
    except subprocess.TimeoutExpired:
        output, code = f"sandbox did not finish within {timeout + 60}s", 124
    if code == 124:
        output += f"\n[timed out after {timeout}s]"
    return code, output


def run_pytest(workspace, pytest_args, grading_dir=None, timeout=300):
    """Run pytest on a copy of `workspace` in the sandbox; return (exit code, output, counts)."""
    mapping = {"ws": workspace}
    if grading_dir:
        mapping["grading"] = grading_dir
    ini = 'printf "[pytest]\\n" > /work/grading/pytest.ini && ' if grading_dir else ""
    code, output = sandbox_run(mapping, ini + 'cd /work/ws && exec timeout -k 5 "$0" python -m pytest -q '
                               '-p no:cacheprovider --tb=short -rfE --timeout=120 "$@"', pytest_args, timeout)
    counts = {}
    summary = [l for l in output.splitlines() if re.search(r"\d+ (passed|failed|errors?|skipped)", l)]
    if summary:
        for n, kind in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)", summary[-1]):
            counts["error" if kind.startswith("error") else kind] = int(n)
    return code, output, counts


def run_hidden_tests(workspace, task_dir, tests_dir=None):
    """Run a test directory (default: the task's hidden tests) against `workspace`, isolated from its conftest."""
    code, output, counts = run_pytest(
        workspace, ["--rootdir=/work/grading", "-c", "/work/grading/pytest.ini", "--confcutdir=/work/grading",
                    "/work/grading"], grading_dir=tests_dir or task_dir / "hidden_tests", timeout=600)
    total = sum(counts.get(k, 0) for k in ("passed", "failed", "error"))
    return {"exit_code": code, "passed": counts.get("passed", 0), "failed": counts.get("failed", 0),
            "errors": counts.get("error", 0), "total": total,
            "score": round(counts.get("passed", 0) / total, 3) if total else 0.0,
            "output": clip(output, 20000)}


# =============================================================================
# Deterministic tools (host side, confined to the workspace)
# =============================================================================

class Workspace:
    """The model's view of the repository. Tracks whether files changed since the last passing full test run."""

    def __init__(self, root, baseline=None, on_green=None):
        self.root = Path(root).resolve()
        self.baseline = baseline or {}
        self.on_green = on_green        # called after a passing full-suite run_tests
        self.dirty = False              # files changed since the last passing full-suite run
        self.green_once = False         # a full-suite run has passed at least once

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

    def syntax_note(self, p):
        """One line for write/edit results: whether a .py file still parses."""
        if p.suffix != ".py":
            return ""
        try:
            ast.parse(self.text(p), filename=self.rel(p))
            return "\nsyntax: OK"
        except SyntaxError as e:
            return f"\nSYNTAX ERROR {self.rel(p)}:{e.lineno}:{e.offset}: {e.msg}\n    {(e.text or '').rstrip()}"

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
        self.dirty = True
        lines = content.count("\n") + (bool(content) and not content.endswith("\n"))
        return f"wrote {self.rel(p)} ({lines} lines)" + self.syntax_note(p)

    def edit_file(self, path, old_string, new_string, replace_all=False):
        p = self.resolve(path)
        text = self.text(p)
        n = text.count(old_string) if old_string else 0
        if n == 0:
            raise ValueError("old_string not found (it must match exactly, including whitespace); read the file again")
        if n > 1 and not replace_all:
            raise ValueError(f"old_string occurs {n} times; add surrounding lines to make it unique or set replace_all")
        new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        p.write_text(new_text)
        self.dirty = True
        # Echo the edited region (first replacement) with 3 lines of context, so the model sees the result.
        first = new_text.count("\n", 0, text.index(old_string)) + 1
        last = first + new_string.count("\n")
        lines = new_text.splitlines()
        lo, hi = max(1, first - 3), min(len(lines), last + 3)
        region = "\n".join(f"{i:>5}\t{lines[i - 1]}" for i in range(lo, hi + 1))
        count = f"{n} replacements" if replace_all and n > 1 else "1 replacement"
        return f"edited {self.rel(p)} ({count}); lines {lo}-{hi} now:\n{region}" + self.syntax_note(p)

    def delete_file(self, path):
        p = self.resolve(path)
        if not p.is_file():
            raise ValueError(f"{path} is not a file")
        p.unlink()
        self.dirty = True
        return f"deleted {self.rel(p)}"

    def show_diff(self, path=None):
        current = snapshot(self.root)
        if path:
            name = self.rel(self.resolve(path, must_exist=False))
            keep = lambda k: k == name or k.startswith(name.rstrip("/") + "/") or name == "."
            before = {k: v for k, v in self.baseline.items() if keep(k)}
            current = {k: v for k, v in current.items() if keep(k)}
        else:
            before = self.baseline
        diff = unified_diff(before, current)
        return clip(diff, 30000) if diff else "(no changes since the start of the task)"

    def check_syntax(self, path=None):
        problems, checked = [], 0
        for p in self.files(self.resolve(path)):
            if p.suffix != ".py":
                continue
            checked += 1
            note = self.syntax_note(p)
            if "SYNTAX ERROR" in note:
                problems.append(note.strip())
        return "\n".join(problems) if problems else f"OK: {checked} Python file(s) parse without errors"

    def run_tests(self, target=None, keyword=None, show_output=False):
        args = []
        if target:
            if target.startswith("-"):
                raise ValueError("target must be a path or node id")
            self.resolve(target.split("::", 1)[0])
            args.append(target)
        if keyword:
            if keyword.startswith("-"):
                raise ValueError("keyword must be a -k expression")
            args += ["-k", keyword]
        if show_output:
            args.append("-s")
        start = time.time()
        code, output, counts = run_pytest(self.root, args)
        failed = [l for l in output.splitlines() if l.startswith(("FAILED ", "ERROR "))]
        summary = ", ".join(f"{v} {k}" for k, v in counts.items()) or "no summary (collection error?)"
        head = f"[pytest exit code {code}, {time.time() - start:.1f}s] {summary}"
        if failed:
            head += "\nFailing:\n" + "\n".join(f"  {l}" for l in failed[:30])
        if not target and not keyword and code == 0:
            self.dirty, self.green_once = False, True
            head += "\nFull suite passed; workspace checkpointed."
            if self.on_green:
                self.on_green()
        return f"{head}\n\n{output}"

    def run_python(self, code, timeout=30):
        timeout = max(1, min(int(timeout or 30), 60))
        rc, output = sandbox_run({"ws": self.root},
                                 'cd /work/ws && PYTHONPATH=/work/ws exec timeout -k 5 "$0" python /work/snippet/main.py',
                                 [], timeout, extra_files={"snippet/main.py": code})
        return f"[exit code {rc}]\n{output or '(no output)'}"


def call_tool(ws, name, args):
    """Run one tool; returns (output text, ok)."""
    handlers = {"list_files": ws.list_files, "read_file": ws.read_file, "outline": ws.outline, "grep": ws.grep,
                "write_file": ws.write_file, "edit_file": ws.edit_file, "delete_file": ws.delete_file,
                "show_diff": ws.show_diff, "check_syntax": ws.check_syntax, "run_tests": ws.run_tests,
                "run_python": ws.run_python}
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
    if args.chat_template_kwargs:
        payload["chat_template_kwargs"] = args.chat_template_kwargs
    req = urllib.request.Request(f"{args.base_url}/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def compact_messages(messages, keep_turns):
    """Shrink the conversation the way harnesses do once it grows: tool outputs and large tool-call arguments
    (file contents, edits) older than the last `keep_turns` assistant turns become one-line stubs.
    Runs only when the prompt crosses a threshold, so the prefix cache stays valid between compactions.
    Returns the number of characters removed."""
    assistant_idx = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    if len(assistant_idx) <= keep_turns:
        return 0
    cutoff = assistant_idx[-keep_turns]
    removed = 0
    for m in messages[2:cutoff]:          # never touch the system prompt or the task
        if m["role"] == "tool" and len(m["content"]) > 300 and not m["content"].startswith("[trimmed"):
            first = m["content"].strip().splitlines()[0][:120] if m["content"].strip() else ""
            stub = f"[trimmed older output, {len(m['content'])} chars; re-run the tool if needed] {first}"
            removed += len(m["content"]) - len(stub)
            m["content"] = stub
        elif m["role"] == "assistant":
            for tc in m.get("tool_calls") or []:
                try:
                    targs = json.loads(tc["function"].get("arguments") or "{}")
                except ValueError:
                    continue
                if not isinstance(targs, dict):
                    continue
                changed = False
                for k, v in targs.items():
                    if isinstance(v, str) and len(v) > 300:
                        targs[k] = f"[{len(v)} chars trimmed]"
                        changed = True
                if changed:
                    new = json.dumps(targs)
                    removed += len(tc["function"]["arguments"]) - len(new)
                    tc["function"]["arguments"] = new
    return removed


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


SCRATCH_NAME = re.compile(r"(^|/)(_?te?mp|scratch|probe|debug|try)[^/]*$", re.I)


def test_names(files):
    """{file: {test function/method names}} for test files in a snapshot."""
    names = {}
    for name, text in files.items():
        base = name.rsplit("/", 1)[-1]
        if not (base.startswith("test_") and base.endswith(".py")):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        names[name] = {n.name for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")}
    return names


def diff_size(before, after):
    added = removed = 0
    for line in unified_diff(before, after).splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"added": added, "removed": removed}


def automated_checks(task_dir, work, baseline, record):
    """Mechanical checks that don't need a human or LLM grader."""
    final = snapshot(work)
    reference = dict(baseline)
    reference.update(snapshot(task_dir / "reference"))
    before_tests, after_tests = test_names(baseline), test_names(final)
    removed_tests = sorted(f"{f}::{t}" for f, names in before_tests.items() for t in names - after_tests.get(f, set()))
    original = run_hidden_tests(work, task_dir, tests_dir=task_dir / "workspace" / "tests")
    calls = [c for t in record["turns"] for c in t["tool_calls"]]
    return {
        "scratch_files": sorted(f for f in set(final) - set(baseline) if SCRATCH_NAME.search(f) or not final[f].strip()),
        "original_tests_removed": removed_tests,
        "original_tests_on_final": {k: original[k] for k in ("passed", "failed", "errors", "total")},
        "diff_lines": diff_size(baseline, final),
        "reference_diff_lines": diff_size(baseline, reference),
        "first_green_turn": record.get("first_green_turn"),
        "tool_calls": len(calls),
        "tool_errors": sum(not c["ok"] for c in calls),
        "tool_error_rate": round(sum(not c["ok"] for c in calls) / len(calls), 3) if calls else 0.0,
        "compactions": sum(1 for t in record["turns"] if t.get("compacted_chars")),
    }


def run_task(task_dir, run_dir, args, api_key, attempt=1):
    task_id = task_dir.name
    work = run_dir / task_id / f"attempt-{attempt}" / "workspace"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(task_dir / "workspace", work)
    checkpoint = work.parent / "last_green"
    shutil.rmtree(checkpoint, ignore_errors=True)
    state = {"turn": 0, "last_green_turn": None, "first_green_turn": None}

    def on_green():
        shutil.rmtree(checkpoint, ignore_errors=True)
        shutil.copytree(work, checkpoint)
        state["last_green_turn"] = state["turn"]
        state["first_green_turn"] = state["first_green_turn"] or state["turn"]

    baseline = snapshot(work)
    ws = Workspace(work, baseline=baseline, on_green=on_green)
    task_text = (task_dir / "TASK.md").read_text()

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{task_text}\n\nRepository files:\n{ws.list_files()}"}]
    record = {"id": task_id, "attempt": attempt, "task": task_text, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "status": None, "finish_summary": None, "turns": [], "tool_counts": {},
              "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "error": None}
    start = time.time()
    nudged = finish_warned = False
    print(f"\n=== {task_id} (attempt {attempt}) ===")
    try:
        for turn in range(1, args.max_turns + 1):
            if time.time() - start > args.task_minutes * 60:
                record["status"] = "time_limit"
                break
            state["turn"] = turn
            left = args.max_turns - turn
            budget = f"\n[turn {turn}/{args.max_turns}; {left} left]"
            if left <= 3:
                budget += " FINAL TURNS: if the full suite passes, call finish now."
            elif left <= 8:
                budget += " Wrap up: stop polishing, make sure the full test suite passes, then call finish."
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
                    if name == "finish" and (ws.dirty or not ws.green_once) and not finish_warned:
                        finish_warned = True
                        why = ("files changed since the last passing full test run" if ws.green_once
                               else "the full test suite has not passed yet")
                        output, ok = (f"Not finished: {why}. Run run_tests with no target, review show_diff, then "
                                      "call finish again (a second finish call is accepted regardless)."), True
                    elif name == "finish":
                        output, ok, finished = "Session finished.", True, True
                        record["finish_summary"] = targs.get("summary")
                    else:
                        output, ok = call_tool(ws, name, targs)
                    output += budget
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
            if args.compact_at_tokens and usage.get("prompt_tokens", 0) > args.compact_at_tokens:
                turn_rec["compacted_chars"] = compact_messages(messages, args.keep_recent_turns)
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
    # Score the last passing checkpoint too when the model changed files after it.
    record["last_green_turn"] = state["last_green_turn"]
    record["first_green_turn"] = state["first_green_turn"]
    record["ended_dirty"] = ws.dirty
    record["hidden_tests_last_green"] = None
    if checkpoint.exists() and snapshot(checkpoint) != snapshot(work):
        record["hidden_tests_last_green"] = run_hidden_tests(checkpoint, task_dir)
    record["checks"] = automated_checks(task_dir, work, baseline, record)
    h, g = record["hidden_tests"], record["hidden_tests_last_green"]
    print(f"  -> {record['status']}, {len(record['turns'])} turns, {record['seconds']:.0f}s, "
          f"{record['usage']['completion_tokens']} output tokens; hidden tests {h['passed']}/{h['total']}"
          + (f" (last checkpoint, turn {state['last_green_turn']}: {g['passed']}/{g['total']})" if g else ""))
    c = record["checks"]
    flags = [f"scratch files {c['scratch_files']}" if c["scratch_files"] else "",
             f"removed tests {c['original_tests_removed']}" if c["original_tests_removed"] else "",
             "original tests fail" if c["original_tests_on_final"]["passed"] < c["original_tests_on_final"]["total"] else ""]
    if any(flags):
        print("     checks: " + "; ".join(f for f in flags if f))
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


def server_sampling_defaults():
    """Best effort: the sampling defaults the chat engine on :8301 announced at startup (vLLM log line)."""
    try:
        name = subprocess.run(["docker", "ps", "--filter", "publish=8301", "--format", "{{.Names}}"],
                              capture_output=True, text=True, timeout=10).stdout.split()[0]
        log = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=30)
        for line in reversed((log.stdout + log.stderr).splitlines()):
            m = re.search(r"overridden by the model's `generation_config.json`: `(\{.*?\})`", line)
            if m:
                return {"engine": name, "source": "generation_config.json", "params": ast.literal_eval(m.group(1))}
        return {"engine": name, "source": "vLLM defaults (no override logged)"}
    except (IndexError, OSError, subprocess.SubprocessError, ValueError, SyntaxError):
        return None


def task_statistics(records):
    """Per task across attempts: how often it fully passed, and the hidden-test score spread."""
    stats = {}
    for task_id in sorted({r["id"] for r in records}):
        runs = [r for r in records if r["id"] == task_id]
        scores = [r["hidden_tests"]["score"] for r in runs]
        best = [max(scores[i], (r.get("hidden_tests_last_green") or {}).get("score", 0)) for i, r in enumerate(runs)]
        mean = sum(scores) / len(scores)
        stats[task_id] = {
            "attempts": len(runs),
            "fully_passing": sum(sc == 1.0 for sc in scores),
            "pass_rate": round(sum(sc == 1.0 for sc in scores) / len(runs), 3),
            "pass_rate_at_best": round(sum(sc == 1.0 for sc in best) / len(runs), 3),
            "score_mean": round(mean, 3),
            "score_min": min(scores), "score_max": max(scores),
            "score_stdev": round((sum((x - mean) ** 2 for x in scores) / len(scores)) ** 0.5, 3),
            "finished": sum(r["status"] == "finished" for r in runs),
            "turns_mean": round(sum(len(r["turns"]) for r in runs) / len(runs), 1),
            "seconds_mean": round(sum(r.get("seconds", 0) for r in runs) / len(runs), 1),
        }
    return stats


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
    parser.add_argument("--chat-template-kwargs", type=json.loads, metavar="JSON",
                        help='Sent with every request, e.g. \'{"reasoning_effort":"xhigh"}\' (vLLM engine; '
                             "default: none, so the engine's --default-chat-template-kwargs apply)")
    parser.add_argument("--only", help="Comma-separated task ids")
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--task-minutes", type=float, default=30, help="Wall-clock limit per task (checked between turns)")
    parser.add_argument("--turn-max-tokens", type=int, default=16384, help="max_tokens per model turn (reasoning included)")
    parser.add_argument("--task-max-tokens", type=int, default=150_000, help="Output-token budget per task")
    parser.add_argument("--repeats", type=int, default=3,
                        help="Attempts per task (default 3; sampling is random, so one run per task is noisy)")
    parser.add_argument("--compact-at-tokens", type=int, default=48_000,
                        help="When a turn's prompt exceeds this many tokens, trim older tool outputs (0 = never)")
    parser.add_argument("--keep-recent-turns", type=int, default=8,
                        help="Turns kept verbatim when compacting (default 8)")
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
        print(f"Resuming {output}: keeping {len(records)} attempt(s)")
    done = {(r["id"], r.get("attempt", 1)) for r in records}
    # Attempt 1 of every task first, then attempt 2, ... so a stopped run still covers all tasks.
    jobs = [(t, a) for a in range(1, args.repeats + 1) for t in tasks if (t.name, a) not in done]
    run_dir = output.with_suffix("")   # final workspaces live next to the JSON
    sampling = {"sent_by_harness": None, "server_defaults": server_sampling_defaults()}

    def save(complete):
        hidden = [r["hidden_tests"] for r in records]
        doc = {"meta": {
            "model": args.model, "base_url": args.base_url, "complete": complete,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "limits": {"max_turns": args.max_turns, "task_minutes": args.task_minutes,
                       "turn_max_tokens": args.turn_max_tokens, "task_max_tokens": args.task_max_tokens},
            "repeats": args.repeats,
            "context": {"compact_at_tokens": args.compact_at_tokens, "keep_recent_turns": args.keep_recent_turns},
            "sampling": sampling, "chat_template_kwargs": args.chat_template_kwargs,
            "system_prompt": SYSTEM_PROMPT, "tools": [t["function"]["name"] for t in TOOLS],
            "attempts": len(records),
            "per_task": task_statistics(records),
            "pass_rate": round(sum(r["hidden_tests"]["total"] > 0 and r["hidden_tests"]["passed"] == r["hidden_tests"]["total"]
                                   for r in records) / len(records), 3) if records else None,
            "finished": sum(r["status"] == "finished" for r in records),
            "hidden_tests_passed": sum(h["passed"] for h in hidden),
            "hidden_tests_total": sum(h["total"] for h in hidden),
            "attempts_fully_passing": sum(h["total"] > 0 and h["passed"] == h["total"] for h in hidden),
            # Best of final state and last passing checkpoint, for tasks ruined by a late edit.
            "attempts_fully_passing_at_best": sum(
                any(t and t["total"] > 0 and t["passed"] == t["total"]
                    for t in (r["hidden_tests"], r.get("hidden_tests_last_green"))) for r in records),
            "completion_tokens": sum(r["usage"]["completion_tokens"] for r in records),
            "seconds": round(sum(r.get("seconds", 0) for r in records), 1),
            "grading": None,
        }, "results": records}
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, output)
        return doc["meta"]

    print(f"Agentic eval: model={args.model!r} via {args.base_url}, {len(tasks)} task(s) x {args.repeats} attempt(s) "
          f"({len(jobs)} to run); sampling: {sampling['server_defaults']}; saving to {output}")
    for task_dir, attempt in jobs:
        records.append(run_task(task_dir, run_dir, args, api_key, attempt))
        save(complete=False)
    m = save(complete=True)
    print(f"\n{m['attempts']} attempts, {m['finished']} finished, {m['attempts_fully_passing']} fully passing "
          f"(pass rate {m['pass_rate']}; {m['attempts_fully_passing_at_best']} counting checkpoints), hidden tests "
          f"{m['hidden_tests_passed']}/{m['hidden_tests_total']}, {m['completion_tokens']} output tokens, {m['seconds']}s")
    for task_id, st in m["per_task"].items():
        print(f"  {task_id:<34} passed {st['fully_passing']}/{st['attempts']}  score mean {st['score_mean']} "
              f"(min {st['score_min']}, max {st['score_max']})  turns {st['turns_mean']}  {st['seconds_mean']}s")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
