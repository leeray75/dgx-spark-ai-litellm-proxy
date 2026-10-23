#!/usr/bin/env python3
"""Tiny todo-list CLI.

Data lives in the JSON file named by $TODO_FILE (default: ./todo.json):
    {"next_id": 3, "items": [{"id": 1, "title": "Buy milk", "done": false,
                             "due": "2026-11-01"}, ...]}

The "due" field is optional; data files written by older versions simply have
no "due" key, which is still perfectly valid.

Commands:
    add TITLE [--due YYYY-MM-DD]   add an item, prints "added ID"
    list [--all] [--overdue] [--today YYYY-MM-DD]
                                   print open items (all items with --all) as
                                   "[ ] ID: TITLE" / "[x] ID: TITLE", with
                                   " (due YYYY-MM-DD)" appended for items that
                                   have a due date.  --overdue keeps only items
                                   that are not done and strictly due before
                                   today (--today, else the system date);
                                   items without a due date are never overdue.
    done ID                        mark an item done, prints "completed ID"
    undo ID                        mark a done item not done, prints "reopened ID"

Exit status: 0 on success, 1 for a missing/ineligible id, 2 for a bad date.
Failed commands never touch the data file.
"""
import argparse
import datetime
import json
import os
import re
import sys

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_date(value):
    """Parse a strict YYYY-MM-DD date into a datetime.date.

    Raises ValueError (with a message containing "invalid date") for a wrong
    format or an impossible calendar date such as 2026-02-30.
    """
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError(f"invalid date {value!r} (expected YYYY-MM-DD)")
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"invalid date {value!r} (no such calendar date)")


def die_bad_date(exc):
    """Report a date-parsing failure and exit with status 2."""
    print(f"error: {exc}", file=sys.stderr)
    sys.exit(2)


def load(path):
    if not os.path.exists(path):
        return {"next_id": 1, "items": []}
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def cmd_add(data, args):
    due = None
    if args.due is not None:
        try:
            due = parse_date(args.due)
        except ValueError as exc:
            die_bad_date(exc)
    item = {"id": data["next_id"], "title": args.title, "done": False}
    if due is not None:
        item["due"] = due.isoformat()
    data["items"].append(item)
    data["next_id"] += 1
    print(f"added {item['id']}")


def _item_due(item):
    """Return the item's due date as a datetime.date, or None."""
    raw = item.get("due")
    if not raw:
        return None
    try:
        return parse_date(raw)
    except ValueError:
        return None


def cmd_list(data, args):
    today = None
    if args.today is not None:
        try:
            today = parse_date(args.today)
        except ValueError as exc:
            die_bad_date(exc)
    if args.overdue and today is None:
        today = datetime.date.today()

    for item in sorted(data["items"], key=lambda item: item["id"]):
        raw_due = item.get("due") or None
        due = _item_due(item)
        if args.overdue:
            # --overdue implies open items only (even together with --all)
            # and a due date strictly before today.
            if item["done"] or due is None or due >= today:
                continue
        elif item["done"] and not args.all:
            continue
        mark = "x" if item["done"] else " "
        line = f"[{mark}] {item['id']}: {item['title']}"
        if raw_due is not None:
            # show the stored value as-is, even if it is not a valid date
            line += f" (due {raw_due})"
        print(line)


def cmd_done(data, args):
    for item in data["items"]:
        if item["id"] == args.id:
            item["done"] = True
            print(f"completed {args.id}")
            return
    print(f"error: no item {args.id}", file=sys.stderr)
    sys.exit(1)


def cmd_undo(data, args):
    for item in data["items"]:
        if item["id"] == args.id:
            if not item["done"]:
                print(f"error: item {args.id} is not done", file=sys.stderr)
                sys.exit(1)
            item["done"] = False
            print(f"reopened {args.id}")
            return
    print(f"error: no item {args.id}", file=sys.stderr)
    sys.exit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="todo")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add")
    p.add_argument("title")
    p.add_argument("--due", metavar="YYYY-MM-DD")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--overdue", action="store_true")
    p.add_argument("--today", metavar="YYYY-MM-DD")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("done")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_done)
    p = sub.add_parser("undo")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_undo)
    args = parser.parse_args(argv)

    path = os.environ.get("TODO_FILE", "todo.json")
    data = load(path)
    args.func(data, args)
    save(path, data)


if __name__ == "__main__":
    main()
