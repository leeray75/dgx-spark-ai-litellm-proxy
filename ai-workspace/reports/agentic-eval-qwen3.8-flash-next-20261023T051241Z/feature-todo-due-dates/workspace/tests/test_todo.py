import datetime
import json
import os
import subprocess
import sys

TODO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "todo.py")


def run(tmp_path, *args):
    env = dict(os.environ, TODO_FILE=str(tmp_path / "todo.json"))
    return subprocess.run([sys.executable, TODO, *args], env=env, capture_output=True, text=True)


def data_file(tmp_path):
    return tmp_path / "todo.json"


def read_data(tmp_path):
    return json.loads(data_file(tmp_path).read_text())


def test_add_list_done(tmp_path):
    assert run(tmp_path, "add", "Buy milk").stdout.strip() == "added 1"
    assert run(tmp_path, "add", "Walk dog").stdout.strip() == "added 2"
    assert run(tmp_path, "done", "1").stdout.strip() == "completed 1"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 2: Walk dog"]
    assert run(tmp_path, "list", "--all").stdout.splitlines() == ["[x] 1: Buy milk", "[ ] 2: Walk dog"]


def test_done_missing(tmp_path):
    r = run(tmp_path, "done", "9")
    assert r.returncode == 1 and "no item 9" in r.stderr


# ---------------------------------------------------------------- due dates

def test_add_without_due_has_no_due_key(tmp_path):
    run(tmp_path, "add", "Buy milk")
    assert read_data(tmp_path)["items"] == [{"id": 1, "title": "Buy milk", "done": False}]


def test_add_with_due_stores_due(tmp_path):
    assert run(tmp_path, "add", "Pay rent", "--due", "2026-11-01").stdout.strip() == "added 1"
    assert read_data(tmp_path)["items"][0]["due"] == "2026-11-01"


def test_list_shows_due_suffix(tmp_path):
    run(tmp_path, "add", "Buy milk")
    run(tmp_path, "add", "Pay rent", "--due", "2026-11-01")
    assert run(tmp_path, "list").stdout.splitlines() == [
        "[ ] 1: Buy milk",
        "[ ] 2: Pay rent (due 2026-11-01)",
    ]
    run(tmp_path, "done", "2")
    assert run(tmp_path, "list", "--all").stdout.splitlines() == [
        "[ ] 1: Buy milk",
        "[x] 2: Pay rent (due 2026-11-01)",
    ]


def test_list_order_is_by_id(tmp_path):
    run(tmp_path, "add", "First", "--due", "2026-01-05")
    run(tmp_path, "add", "Second")
    run(tmp_path, "add", "Third", "--due", "2026-01-01")
    assert run(tmp_path, "list").stdout.splitlines() == [
        "[ ] 1: First (due 2026-01-05)",
        "[ ] 2: Second",
        "[ ] 3: Third (due 2026-01-01)",
    ]


def test_add_invalid_date_exits_2_and_leaves_file_untouched(tmp_path):
    run(tmp_path, "add", "Keep", "--due", "2026-01-01")
    before = data_file(tmp_path).read_text()
    for bad in ("2026-02-30", "11-01-2026", "2026-11-1", "20261101", "2026-13-01", "today", ""):
        r = run(tmp_path, "add", "Pay rent", "--due", bad)
        assert r.returncode == 2, (bad, r.returncode)
        assert "invalid date" in r.stderr, (bad, r.stderr)
        assert r.stdout == ""
    assert data_file(tmp_path).read_text() == before
    assert [i["title"] for i in read_data(tmp_path)["items"]] == ["Keep"]


def test_add_invalid_date_before_file_created(tmp_path):
    r = run(tmp_path, "add", "Pay rent", "--due", "2026-02-30")
    assert r.returncode == 2 and "invalid date" in r.stderr
    assert not data_file(tmp_path).exists()


# ------------------------------------------------------------- overdue filter

def make_mixed(tmp_path):
    run(tmp_path, "add", "no due")                 # 1
    run(tmp_path, "add", "past", "--due", "2026-10-31")   # 2
    run(tmp_path, "add", "today", "--due", "2026-11-01")  # 3
    run(tmp_path, "add", "future", "--due", "2026-11-02")  # 4
    run(tmp_path, "add", "done past", "--due", "2026-10-01")  # 5
    run(tmp_path, "done", "5")


def test_overdue_uses_today_option(tmp_path):
    make_mixed(tmp_path)
    out = run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout.splitlines()
    # not done, strictly before today, has a due date
    assert out == ["[ ] 2: past (due 2026-10-31)"]


def test_overdue_excludes_done_and_no_due(tmp_path):
    run(tmp_path, "add", "no due", "--due", "2020-01-01")
    run(tmp_path, "done", "1")
    run(tmp_path, "add", "still open")
    out = run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout
    assert out.strip() == ""


def test_overdue_boundary_is_strict(tmp_path):
    run(tmp_path, "add", "x", "--due", "2026-11-01")
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout.strip() == ""
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-02").stdout.splitlines() == [
        "[ ] 1: x (due 2026-11-01)"
    ]


def test_overdue_with_all_behaves_like_overdue(tmp_path):
    make_mixed(tmp_path)
    overdue = run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout
    both = run(tmp_path, "list", "--overdue", "--all", "--today", "2026-11-01").stdout
    assert both == overdue
    assert both.splitlines() == ["[ ] 2: past (due 2026-10-31)"]


def test_overdue_defaults_to_system_date(tmp_path):
    today = datetime.date.today()
    past = (today - datetime.timedelta(days=1)).isoformat()
    future = (today + datetime.timedelta(days=1)).isoformat()
    run(tmp_path, "add", "late", "--due", past)
    run(tmp_path, "add", "soon", "--due", future)
    run(tmp_path, "add", "none")
    assert run(tmp_path, "list", "--overdue").stdout.splitlines() == [f"[ ] 1: late (due {past})"]


def test_list_invalid_today_exits_2(tmp_path):
    make_mixed(tmp_path)
    before = data_file(tmp_path).read_text()
    r = run(tmp_path, "list", "--overdue", "--today", "nope")
    assert r.returncode == 2 and "invalid date" in r.stderr
    assert data_file(tmp_path).read_text() == before


# ------------------------------------------------------------------- undo

def test_undo_reopens_done_item(tmp_path):
    run(tmp_path, "add", "Buy milk")
    run(tmp_path, "done", "1")
    assert run(tmp_path, "undo", "1").stdout.strip() == "reopened 1"
    assert read_data(tmp_path)["items"][0]["done"] is False
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Buy milk"]


def test_undo_keeps_due_date(tmp_path):
    run(tmp_path, "add", "Pay rent", "--due", "2026-11-01")
    run(tmp_path, "done", "1")
    run(tmp_path, "undo", "1")
    assert read_data(tmp_path)["items"][0]["due"] == "2026-11-01"
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Pay rent (due 2026-11-01)"]


def test_undo_not_done_is_error(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = data_file(tmp_path).read_text()
    r = run(tmp_path, "undo", "1")
    assert r.returncode == 1
    assert r.stderr.strip() == "error: item 1 is not done"
    assert r.stdout == ""
    assert data_file(tmp_path).read_text() == before


def test_undo_missing_item_is_error(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = data_file(tmp_path).read_text()
    r = run(tmp_path, "undo", "42")
    assert r.returncode == 1
    assert r.stderr.strip() == "error: no item 42"
    assert r.stdout == ""
    assert data_file(tmp_path).read_text() == before


def test_undo_empty_store_is_error(tmp_path):
    r = run(tmp_path, "undo", "1")
    assert r.returncode == 1 and r.stderr.strip() == "error: no item 1"


def test_failed_done_leaves_file_untouched(tmp_path):
    run(tmp_path, "add", "Buy milk")
    before = data_file(tmp_path).read_text()
    run(tmp_path, "done", "99")
    assert data_file(tmp_path).read_text() == before


def test_today_without_overdue_does_not_filter(tmp_path):
    run(tmp_path, "add", "past", "--due", "2000-01-01")
    run(tmp_path, "add", "future", "--due", "2999-01-01")
    assert run(tmp_path, "list", "--today", "2026-11-01").stdout.splitlines() == [
        "[ ] 1: past (due 2000-01-01)",
        "[ ] 2: future (due 2999-01-01)",
    ]


def test_leap_day_dates(tmp_path):
    assert run(tmp_path, "add", "leap", "--due", "2028-02-29").returncode == 0
    r = run(tmp_path, "add", "not leap", "--due", "2026-02-29")
    assert r.returncode == 2 and "invalid date" in r.stderr
    assert [i["title"] for i in read_data(tmp_path)["items"]] == ["leap"]


def test_overdue_on_empty_store(tmp_path):
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout == ""


def test_overdue_only_shows_open_items_even_when_done_and_past(tmp_path):
    run(tmp_path, "add", "a", "--due", "2020-01-01")
    run(tmp_path, "add", "b", "--due", "2020-01-02")
    run(tmp_path, "done", "1")
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout.splitlines() == [
        "[ ] 2: b (due 2020-01-02)"
    ]


# ------------------------------------------------------- backwards compat

def test_legacy_file_without_due_field(tmp_path):
    data_file(tmp_path).write_text(
        json.dumps({"next_id": 3, "items": [
            {"id": 1, "title": "Buy milk", "done": False},
            {"id": 2, "title": "Old and done", "done": True},
        ]})
    )
    assert run(tmp_path, "list").stdout.splitlines() == ["[ ] 1: Buy milk"]
    assert run(tmp_path, "list", "--all").stdout.splitlines() == [
        "[ ] 1: Buy milk",
        "[x] 2: Old and done",
    ]
    assert run(tmp_path, "list", "--overdue", "--today", "2026-11-01").stdout == ""
    assert run(tmp_path, "add", "New").stdout.strip() == "added 3"
    assert run(tmp_path, "undo", "2").stdout.strip() == "reopened 2"
    assert run(tmp_path, "list", "--all").stdout.splitlines() == [
        "[ ] 1: Buy milk",
        "[ ] 2: Old and done",
        "[ ] 3: New",
    ]
