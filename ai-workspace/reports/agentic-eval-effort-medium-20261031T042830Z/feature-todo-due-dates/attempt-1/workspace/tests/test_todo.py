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


def read_data(tmp_path):
    import json

    p = tmp_path / "todo.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def test_add_due_stored(tmp_path):
    assert run(tmp_path, "add", "Pay rent", "--due", "2026-11-01").stdout.strip() == "added 1"
    assert run(tmp_path, "add", "Buy milk").stdout.strip() == "added 2"
    data = read_data(tmp_path)
    assert data["items"][0]["due"] == "2026-11-01"
    assert "due" not in data["items"][1]


def test_list_shows_due(tmp_path):
    run(tmp_path, "add", "Pay rent", "--due", "2026-11-01")
    run(tmp_path, "add", "Buy milk")
    assert run(tmp_path, "list").stdout.splitlines() == [
        "[ ] 1: Pay rent (due 2026-11-01)",
        "[ ] 2: Buy milk",
    ]


def test_add_invalid_date(tmp_path):
    assert run(tmp_path, "add", "ok").stdout.strip() == "added 1"
    before = read_data(tmp_path)
    for bad in ("2026-02-30", "11-01-2026", "2026-11-1", "not-a-date", "2026-13-01"):
        r = run(tmp_path, "add", "bad", "--due", bad)
        assert r.returncode == 2, bad
        assert "invalid date" in r.stderr, bad
        assert r.stdout == ""
    assert read_data(tmp_path) == before


def test_list_overdue(tmp_path):
    run(tmp_path, "add", "over", "--due", "2026-01-31")
    run(tmp_path, "add", "today", "--due", "2026-02-01")
    run(tmp_path, "add", "future", "--due", "2026-02-02")
    run(tmp_path, "add", "nodue")
    run(tmp_path, "done", "1")  # done even though overdue
    out = run(tmp_path, "list", "--overdue", "--today", "2026-02-01").stdout.splitlines()
    assert out == []
    run(tmp_path, "undo", "1")
    out = run(tmp_path, "list", "--overdue", "--today", "2026-02-01").stdout.splitlines()
    assert out == ["[ ] 1: over (due 2026-01-31)"]


def test_list_overdue_with_all(tmp_path):
    run(tmp_path, "add", "over", "--due", "2026-01-31")
    run(tmp_path, "add", "doneover", "--due", "2026-01-30")
    run(tmp_path, "done", "2")
    expected = ["[ ] 1: over (due 2026-01-31)"]
    assert run(tmp_path, "list", "--overdue", "--today", "2026-02-01").stdout.splitlines() == expected
    assert (
        run(tmp_path, "list", "--overdue", "--all", "--today", "2026-02-01").stdout.splitlines()
        == expected
    )


def test_list_overdue_uses_system_date(tmp_path):
    from datetime import date, timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    run(tmp_path, "add", "over", "--due", yesterday)
    run(tmp_path, "add", "future", "--due", tomorrow)
    assert run(tmp_path, "list", "--overdue").stdout.splitlines() == [
        f"[ ] 1: over (due {yesterday})"
    ]


def test_undo(tmp_path):
    run(tmp_path, "add", "Buy milk")
    run(tmp_path, "done", "1")
    assert run(tmp_path, "undo", "1").stdout.strip() == "reopened 1"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Buy milk"]
    assert read_data(tmp_path)["items"][0]["done"] is False


def test_undo_not_done(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = read_data(tmp_path)
    r = run(tmp_path, "undo", "1")
    assert r.returncode == 1
    assert r.stderr.strip() == "error: item 1 is not done"
    assert r.stdout == ""
    assert read_data(tmp_path) == before


def test_undo_missing(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = read_data(tmp_path)
    r = run(tmp_path, "undo", "9")
    assert r.returncode == 1
    assert r.stderr.strip() == "error: no item 9"
    assert read_data(tmp_path) == before


def test_legacy_file_without_due(tmp_path):
    import json

    (tmp_path / "todo.json").write_text(
        json.dumps({"next_id": 2, "items": [{"id": 1, "title": "Old", "done": False}]})
    )
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Old"]
    assert run(tmp_path, "list", "--overdue", "--today", "2026-02-01").stdout == ""
    assert run(tmp_path, "add", "New", "--due", "2026-02-05").stdout.strip() == "added 2"
    assert run(tmp_path, "list").stdout.splitlines() == [
        "[ ] 1: Old",
        "[ ] 2: New (due 2026-02-05)",
    ]
