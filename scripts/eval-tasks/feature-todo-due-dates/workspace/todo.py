#!/usr/bin/env python3
"""Tiny todo-list CLI.

Data lives in the JSON file named by $TODO_FILE (default: ./todo.json):
    {"next_id": 3, "items": [{"id": 1, "title": "Buy milk", "done": false}, ...]}

Commands:
    add TITLE          add an item, prints "added ID"
    list [--all]       print open items (all items with --all) as "[ ] ID: TITLE" / "[x] ID: TITLE"
    done ID            mark an item done, prints "completed ID"
"""
import argparse
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


def cmd_add(data, args):
    item = {"id": data["next_id"], "title": args.title, "done": False}
    data["items"].append(item)
    data["next_id"] += 1
    print(f"added {item['id']}")


def cmd_list(data, args):
    for item in data["items"]:
        if item["done"] and not args.all:
            continue
        mark = "x" if item["done"] else " "
        print(f"[{mark}] {item['id']}: {item['title']}")


def cmd_done(data, args):
    for item in data["items"]:
        if item["id"] == args.id:
            item["done"] = True
            print(f"completed {args.id}")
            return
    print(f"error: no item {args.id}", file=sys.stderr)
    sys.exit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="todo")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add")
    p.add_argument("title")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("done")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_done)
    args = parser.parse_args(argv)

    path = os.environ.get("TODO_FILE", "todo.json")
    data = load(path)
    args.func(data, args)
    save(path, data)


if __name__ == "__main__":
    main()
