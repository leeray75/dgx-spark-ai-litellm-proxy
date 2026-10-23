# Feature: due dates, overdue filter and undo for the todo CLI

`todo.py` is a small todo-list CLI (see its docstring). Add the following, keeping everything
that works today working, including data files written by the current version (they have no
`due` field).

1. **Due dates.** `add TITLE --due YYYY-MM-DD` stores the date on the item as
   `"due": "YYYY-MM-DD"`. `--due` is optional; items added without it have no due date.
   An invalid date (wrong format or impossible date such as `2026-02-30`) must print a message
   containing `invalid date` to **stderr**, exit with status **2**, and leave the data file unchanged.
2. **Listing.** `list` prints items with a due date as `[ ] 3: Pay rent (due 2026-11-01)`;
   items without one print exactly as before. Order stays by id.
3. **Overdue filter.** `list --overdue` shows only items that are **not done** and whose due date is
   **strictly before** today. "Today" is `--today YYYY-MM-DD` when given (an option of `list`), otherwise
   the system date. Items without a due date are never overdue. `--overdue` combined with `--all`
   behaves like `--overdue`.
4. **Undo.** `undo ID` marks a done item as not done and prints `reopened ID`. If the item exists but
   is not done: print `error: item ID is not done` to stderr, exit 1. If it doesn't exist:
   print `error: no item ID` to stderr, exit 1. Failed commands must not change the data file.

Add tests for the new behaviour in `tests/`.
