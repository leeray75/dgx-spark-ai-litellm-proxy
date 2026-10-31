#!/usr/bin/env python3
"""Tiny todo-list CLI.

Data lives in the JSON file named by $TODO_FILE (default: ./todo.json):
    {"next_id": 3, "items": [{"id": 1, "title": "Buy milk", "done": false,
                              "due": "2026-11-01"}, ...]}

The "due" field is optional (older data files do not have it).

Commands:
    add TITLE [--due YYYY-MM-DD]   add an item, prints "added ID"
    list [--all] [--overdue] [--today YYYY-MM-DD]
                                   print open items (all items with --all) as
                                   "[ ] ID: TITLE" / "[x] ID: TITLE", with
                                   " (due YYYY-MM-DD)" appended for items that
                                   have a due date. --overdue keeps only items
                                   that are not done and due before today.
    done ID                        mark an item done, prints "completed ID"
    undo ID                        mark a done item not done, prints "reopened ID"
"""
import argparse
import datetime
import json
import os
import re
import sys

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load(path):
    if not os.path.exists(path):
        return {"next_id": 1, "items": []}
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def parse_date(value, label="--due"):
    """Return the datetime.date for a strict YYYY-MM-DD string.

    On bad input, report to stderr and exit with status 2.
    """

    def fail():
        print(
            f"error: invalid date for {label}: {value!r} (expected YYYY-MM-DD)",
            file=sys.stderr,
        )
        sys.exit(2)

    if not DATE_RE.match(value or ""):
        fail()
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        fail()


def find(data, item_id):
    for item in data["items"]:
        if item["id"] == item_id:
            return item
    return None


def cmd_add(data, args):
    due = None
    if args.due is not None:
        parse_date(args.due)  # exits(2) on bad input, before touching data
        due = args.due
    item = {"id": data["next_id"], "title": args.title, "done": False}
    if due is not None:
        item["due"] = due
    data["items"].append(item)
    data["next_id"] += 1
    print(f"added {item['id']}")


def cmd_list(data, args):
    today = None
    if args.overdue:
        today = parse_date(args.today, "today") if args.today else datetime.date.today()
    for item in data["items"]:
        if args.overdue:
            due = item.get("due")
            if item["done"] or not due:
                continue
            if parse_date(due) >= today:
                continue
        elif item["done"] and not args.all:
            continue
        mark = "x" if item["done"] else " "
        line = f"[{mark}] {item['id']}: {item['title']}"
        if item.get("due"):
            line += f" (due {item['due']})"
        print(line)


def cmd_done(data, args):
    item = find(data, args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        sys.exit(1)
    item["done"] = True
    print(f"completed {args.id}")


def cmd_undo(data, args):
    item = find(data, args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        sys.exit(1)
    if not item["done"]:
        print(f"error: item {args.id} is not done", file=sys.stderr)
        sys.exit(1)
    item["done"] = False
    print(f"reopened {args.id}")


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
