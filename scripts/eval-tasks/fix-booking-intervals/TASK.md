# Bug: meeting rooms shown as free while booked

The booking service's availability page is wrong. Reports from users:

- Room 4 had bookings 09:00–09:30 and 09:30–10:00 but the page offered a 0-minute gap at 09:30.
- A room booked 08:00–12:00 *and* 09:00–09:30 showed as free from 09:30 to 12:00.
- Bookings that were entered out of order produced garbage availability.
- Asking for slots of at least 30 minutes hid a free slot that was exactly 30 minutes long.
- The "busy minutes" figure on the dashboard is sometimes negative when a booking starts before
  the business day or ends after it.

All of these come from `scheduling/intervals.py`. Fix the module so that **every function behaves
exactly as its docstring says** (the docstrings are the specification; don't change them).
Keep the existing tests in `tests/` passing and add tests for the cases you fix.
