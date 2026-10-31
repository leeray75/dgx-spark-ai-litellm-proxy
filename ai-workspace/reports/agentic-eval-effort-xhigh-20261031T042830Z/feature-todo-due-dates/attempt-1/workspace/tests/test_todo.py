import json
import os
import subprocess
import sys

TODO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "todo.py")


def run(tmp_path, *args):
    env = dict(os.environ, TODO_FILE=str(tmp_path / "todo.json"))
    return subprocess.run([sys.executable, TODO, *args], env=env, capture_output=True, text=True)


def data_file(tmp_path):
    return (tmp_path / "todo.json").read_text()


def test_add_list_done(tmp_path):
    assert run(tmp_path, "add", "Buy milk").stdout.strip() == "added 1"
    assert run(tmp_path, "add", "Walk dog").stdout.strip() == "added 2"
    assert run(tmp_path, "done", "1").stdout.strip() == "completed 1"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 2: Walk dog"]
    assert run(tmp_path, "list", "--all").stdout.splitlines() == ["[x] 1: Buy milk", "[ ] 2: Walk dog"]


def test_done_missing(tmp_path):
    r = run(tmp_path, "done", "9")
    assert r.returncode == 1 and "no item 9" in r.stderr


# --- due dates -------------------------------------------------------------

def test_add_due_stores_field(tmp_path):
    run(tmp_path, "add", "Pay rent", "--due", "2026-11-01")
    run(tmp_path, "add", "Buy milk")
    data = json.loads(data_file(tmp_path))
    assert data["items"][0]["due"] == "2026-11-01"
    assert "due" not in data["items"][1]


def test_list_shows_due(tmp_path):
    run(tmp_path, "add", "Pay rent", "--due", "2026-11-01")
    run(tmp_path, "add", "Buy milk")
    assert run(tmp_path, "list").stdout.splitlines() == [
        "[ ] 1: Pay rent (due 2026-11-01)",
        "[ ] 2: Buy milk",
    ]
    run(tmp_path, "done", "1")
    assert run(tmp_path, "list", "--all").stdout.splitlines() == [
        "[x] 1: Pay rent (due 2026-11-01)",
        "[ ] 2: Buy milk",
    ]


def test_add_invalid_date_format(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = data_file(tmp_path)
    r = run(tmp_path, "add", "Pay rent", "--due", "2026/11/01")
    assert r.returncode == 2
    assert "invalid date" in r.stderr
    assert "Pay rent" not in r.stdout
    assert data_file(tmp_path) == before


def test_add_invalid_calendar_date(tmp_path):
    r = run(tmp_path, "add", "Pay rent", "--due", "2026-02-30")
    assert r.returncode == 2
    assert "invalid date" in r.stderr
    assert not (tmp_path / "todo.json").exists() or data_file(tmp_path) == '{"next_id": 1, "items": []}'


# --- overdue ---------------------------------------------------------------

def test_overdue_strictly_before_today(tmp_path):
    run(tmp_path, "add", "over", "--due", "2026-10-31")
    run(tmp_path, "add", "today", "--due", "2026-11-01")
    run(tmp_path, "add", "future", "--due", "2026-11-02")
    run(tmp_path, "add", "nodue")
    out = run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout.splitlines()
    assert out == ["[ ] 1: over (due 2026-10-31)"]


def test_overdue_skips_done_items(tmp_path):
    run(tmp_path, "add", "over", "--due", "2026-10-31")
    run(tmp_path, "add", "done too", "--due", "2026-10-30")
    run(tmp_path, "done", "2")
    out = run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout.splitlines()
    assert out == ["[ ] 1: over (due 2026-10-31)"]


def test_overdue_ignores_items_without_due(tmp_path):
    run(tmp_path, "add", "nodue")
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout == ""


def test_overdue_with_all(tmp_path):
    run(tmp_path, "add", "over", "--due", "2026-10-01")
    run(tmp_path, "add", "later", "--due", "2026-12-01")
    run(tmp_path, "done", "2")
    for extra in ([], ["--all"]):
        out = run(tmp_path, "list", "--overdue", "--today", "2026-11-01", *extra).stdout.splitlines()
        assert out == ["[ ] 1: over (due 2026-10-01)"]


def test_overdue_defaults_to_system_date(tmp_path):
    run(tmp_path, "add", "ancient", "--due", "1999-01-01")
    run(tmp_path, "add", "far future", "--due", "2999-01-01")
    out = run(tmp_path, "list", "--overdue").stdout.splitlines()
    assert out == ["[ ] 1: ancient (due 1999-01-01)"]


def test_list_invalid_today(tmp_path):
    run(tmp_path, "add", "x", "--due", "2026-01-01")
    before = data_file(tmp_path)
    r = run(tmp_path, "list", "--overdue", "--today", "not-a-date")
    assert r.returncode == 2 and "invalid date" in r.stderr
    assert data_file(tmp_path) == before


# --- undo ------------------------------------------------------------------

def test_undo_reopens(tmp_path):
    run(tmp_path, "add", "Buy milk")
    run(tmp_path, "done", "1")
    assert run(tmp_path, "undo", "1").stdout.strip() == "reopened 1"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Buy milk"]
    assert json.loads(data_file(tmp_path))["items"][0]["done"] is False


def test_undo_not_done(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = data_file(tmp_path)
    r = run(tmp_path, "undo", "1")
    assert r.returncode == 1
    assert r.stderr.strip() == "error: item 1 is not done"
    assert r.stdout == ""
    assert data_file(tmp_path) == before


def test_undo_missing_item(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = data_file(tmp_path)
    r = run(tmp_path, "undo", "9")
    assert r.returncode == 1
    assert r.stderr.strip() == "error: no item 9"
    assert data_file(tmp_path) == before


# --- backwards compatibility ------------------------------------------------

def test_legacy_file_without_due_field(tmp_path):
    (tmp_path / "todo.json").write_text(
        json.dumps({"next_id": 3, "items": [
            {"id": 1, "title": "Buy milk", "done": False},
            {"id": 2, "title": "Old done", "done": True},
        ]})
    )
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Buy milk"]
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout == ""
    r = run(tmp_path, "add", "New", "--due", "2026-11-05")
    assert r.stdout.strip() == "added 3"
    assert run(tmp_path, "list").stdout.splitlines() == [
        "[ ] 1: Buy milk",
        "[ ] 3: New (due 2026-11-05)",
    ]
    assert run(tmp_path, "undo", "1").returncode == 1
