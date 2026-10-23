import os
import subprocess
import sys

TODO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "todo.py")


def run(tmp_path, *args):
    env = dict(os.environ, TODO_FILE=str(tmp_path / "todo.json"))
    return subprocess.run([sys.executable, TODO, *args], env=env, capture_output=True, text=True)


def test_add_list_done(tmp_path):
    assert run(tmp_path, "add", "Buy milk").stdout.strip() == "added 1"
    assert run(tmp_path, "add", "Walk dog").stdout.strip() == "added 2"
    assert run(tmp_path, "done", "1").stdout.strip() == "completed 1"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 2: Walk dog"]
    assert run(tmp_path, "list", "--all").stdout.splitlines() == ["[x] 1: Buy milk", "[ ] 2: Walk dog"]


def test_done_missing(tmp_path):
    r = run(tmp_path, "done", "9")
    assert r.returncode == 1 and "no item 9" in r.stderr
