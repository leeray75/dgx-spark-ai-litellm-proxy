import json
import os
import subprocess
import sys

TODO = os.path.join(os.getcwd(), "todo.py")


def run(tmp_path, *args):
    env = dict(os.environ, TODO_FILE=str(tmp_path / "todo.json"))
    return subprocess.run([sys.executable, TODO, *args], env=env, capture_output=True, text=True)


def data(tmp_path):
    return json.loads((tmp_path / "todo.json").read_text())


def test_existing_behaviour(tmp_path):
    assert run(tmp_path, "add", "Buy milk").stdout.strip() == "added 1"
    assert run(tmp_path, "add", "Walk dog").stdout.strip() == "added 2"
    assert run(tmp_path, "done", "1").stdout.strip() == "completed 1"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 2: Walk dog"]
    assert run(tmp_path, "list", "--all").stdout.splitlines() == ["[x] 1: Buy milk", "[ ] 2: Walk dog"]


def test_add_with_due_and_list(tmp_path):
    run(tmp_path, "add", "Pay rent", "--due", "2026-11-01")
    run(tmp_path, "add", "No date")
    items = data(tmp_path)["items"]
    assert items[0]["due"] == "2026-11-01"
    assert items[1].get("due") is None
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Pay rent (due 2026-11-01)", "[ ] 2: No date"]


def test_invalid_dates_rejected_without_change(tmp_path):
    run(tmp_path, "add", "First")
    before = (tmp_path / "todo.json").read_text()
    for bad in ("2026-02-30", "2026/01/01", "tomorrow", "2026-1-5"):
        r = run(tmp_path, "add", "Bad", "--due", bad)
        assert r.returncode == 2, bad
        assert "invalid date" in r.stderr, bad
        assert (tmp_path / "todo.json").read_text() == before, bad


def test_overdue_filter(tmp_path):
    run(tmp_path, "add", "Past", "--due", "2026-10-01")
    run(tmp_path, "add", "Today", "--due", "2026-10-23")
    run(tmp_path, "add", "Future", "--due", "2026-12-01")
    run(tmp_path, "add", "Undated")
    run(tmp_path, "add", "Past but done", "--due", "2026-01-01")
    run(tmp_path, "done", "5")
    out = run(tmp_path, "list", "--overdue", "--today", "2026-10-23").stdout.splitlines()
    assert out == ["[ ] 1: Past (due 2026-10-01)"]
    out = run(tmp_path, "list", "--overdue", "--all", "--today", "2026-10-23").stdout.splitlines()
    assert out == ["[ ] 1: Past (due 2026-10-01)"]
    out = run(tmp_path, "list", "--overdue", "--today", "2026-12-02").stdout.splitlines()
    assert out == ["[ ] 1: Past (due 2026-10-01)", "[ ] 2: Today (due 2026-10-23)", "[ ] 3: Future (due 2026-12-01)"]


def test_overdue_uses_system_date_by_default(tmp_path):
    run(tmp_path, "add", "Ancient", "--due", "2000-01-01")
    run(tmp_path, "add", "Far future", "--due", "2999-01-01")
    assert run(tmp_path, "list", "--overdue").stdout.splitlines() == ["[ ] 1: Ancient (due 2000-01-01)"]


def test_undo(tmp_path):
    run(tmp_path, "add", "A")
    run(tmp_path, "add", "B")
    run(tmp_path, "done", "1")
    r = run(tmp_path, "undo", "1")
    assert r.returncode == 0 and r.stdout.strip() == "reopened 1"
    assert data(tmp_path)["items"][0]["done"] is False
    before = (tmp_path / "todo.json").read_text()
    r = run(tmp_path, "undo", "2")
    assert r.returncode == 1 and "error: item 2 is not done" in r.stderr
    r = run(tmp_path, "undo", "7")
    assert r.returncode == 1 and "error: no item 7" in r.stderr
    assert (tmp_path / "todo.json").read_text() == before


def test_old_data_file_without_due(tmp_path):
    (tmp_path / "todo.json").write_text(json.dumps(
        {"next_id": 3, "items": [{"id": 1, "title": "Old", "done": False}, {"id": 2, "title": "Older", "done": True}]}))
    assert run(tmp_path, "list", "--all").stdout.splitlines() == ["[ ] 1: Old", "[x] 2: Older"]
    assert run(tmp_path, "list", "--overdue", "--today", "2026-10-23").stdout.strip() == ""
    assert run(tmp_path, "add", "New", "--due", "2026-10-30").stdout.strip() == "added 3"
