#!/usr/bin/env python3
"""Tiny todo-list CLI.

Data lives in the JSON file named by $TODO_FILE (default: ./todo.json):
    {"next_id": 3, "items": [{"id": 1, "title": "Buy milk", "done": false}, ...]}

Commands:
    add TITLE [--due YYYY-MM-DD]  add an item, prints "added ID"
    list [--all] [--overdue] [--today YYYY-MM-DD]
                       print open items (all items with --all) as
                       "[ ] ID: TITLE" / "[x] ID: TITLE", with " (due DATE)"
                       appended for items that have a due date;
                       --overdue shows only not-done items due before today
    done ID            mark an item done, prints "completed ID"
    undo ID            mark a done item not done, prints "reopened ID"
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime


def parse_date(s):
    """Parse a strict YYYY-MM-DD date, raising ValueError otherwise."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError(f"bad format: {s!r}")
    return datetime.strptime(s, "%Y-%m-%d").date()


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
        except ValueError:
            print(f"error: invalid date {args.due}", file=sys.stderr)
            sys.exit(2)
    item = {"id": data["next_id"], "title": args.title, "done": False}
    if due is not None:
        item["due"] = due.strftime("%Y-%m-%d")
    data["items"].append(item)
    data["next_id"] += 1
    print(f"added {item['id']}")


def cmd_list(data, args):
    today = date.today()
    if args.overdue and args.today is not None:
        try:
            today = parse_date(args.today)
        except ValueError:
            print(f"error: invalid date {args.today}", file=sys.stderr)
            sys.exit(2)
    for item in data["items"]:
        if args.overdue:
            if item["done"] or "due" not in item:
                continue
            try:
                due = parse_date(item["due"])
            except ValueError:
                continue
            if due >= today:
                continue
        elif item["done"] and not args.all:
            continue
        mark = "x" if item["done"] else " "
        line = f"[{mark}] {item['id']}: {item['title']}"
        if "due" in item:
            line += f" (due {item['due']})"
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
    p.add_argument("--due", default=None)
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--overdue", action="store_true")
    p.add_argument("--today", default=None)
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
