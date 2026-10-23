#!/usr/bin/env python3
"""Tiny todo-list CLI (reference solution)."""
import argparse
import datetime
import json
import os
import sys


def load(path):
    if not os.path.exists(path):
        return {"next_id": 1, "items": []}
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def iso_date(value):
    try:
        if len(value) != 10:
            raise ValueError
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date '{value}' (expected YYYY-MM-DD)")


def cmd_add(data, args):
    item = {"id": data["next_id"], "title": args.title, "done": False}
    if args.due:
        item["due"] = args.due.isoformat()
    data["items"].append(item)
    data["next_id"] += 1
    print(f"added {item['id']}")


def cmd_list(data, args):
    today = args.today or datetime.date.today()
    for item in data["items"]:
        due = item.get("due")
        if args.overdue:
            if item["done"] or not due or datetime.date.fromisoformat(due) >= today:
                continue
        elif item["done"] and not args.all:
            continue
        mark = "x" if item["done"] else " "
        suffix = f" (due {due})" if due else ""
        print(f"[{mark}] {item['id']}: {item['title']}{suffix}")


def find(data, item_id):
    for item in data["items"]:
        if item["id"] == item_id:
            return item
    print(f"error: no item {item_id}", file=sys.stderr)
    sys.exit(1)


def cmd_done(data, args):
    find(data, args.id)["done"] = True
    print(f"completed {args.id}")


def cmd_undo(data, args):
    item = find(data, args.id)
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
    p.add_argument("--due", type=iso_date)
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--overdue", action="store_true")
    p.add_argument("--today", type=iso_date)
    p.set_defaults(func=cmd_list)
    for name, func in (("done", cmd_done), ("undo", cmd_undo)):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)

    path = os.environ.get("TODO_FILE", "todo.json")
    data = load(path)
    args.func(data, args)
    save(path, data)


if __name__ == "__main__":
    main()
