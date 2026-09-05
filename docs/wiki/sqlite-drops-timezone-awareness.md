# SQLite silently drops timezone-awareness on `DateTime(timezone=True)` columns

## Summary

Any code comparing a `DateTime(timezone=True)` column's value against a
timezone-aware Python `datetime` (e.g. `datetime.now(timezone.utc)`)
works fine against real Postgres, but raises `TypeError: can't compare
offset-naive and offset-aware datetimes` when the same code runs against
this project's default local test backend (in-memory SQLite, used
whenever `TEST_DATABASE_URL` isn't set). This has now hit this codebase
twice independently: `app/services/auth_service.py`'s `locked_until`
check, and `app/services/square_service.py`'s `needs_token_refresh()`.

## Why happened?

SQLAlchemy's `DateTime(timezone=True)` is a real, honored type against
Postgres (which has a native `timestamptz` column type) — values come
back tz-aware. SQLite has no native timezone-aware timestamp type at all;
SQLAlchemy's SQLite dialect stores the value as a plain string and
returns it back naive, regardless of what the column type declares.
Nothing raises a warning when this happens — the column looks identical
in both backends until two datetimes are actually compared with `>`,
`<`, `>=`, etc.

## Rule

If you're comparing a `DateTime(timezone=True)` column's value against
`datetime.now(timezone.utc)` (or similar), that code cannot be
considered verified by a plain local `pytest` run — it must also pass
against real Postgres (`TEST_DATABASE_URL` set) before trusting it. A
green local SQLite run proves nothing about this specific class of bug;
it can pass locally and still be completely broken (or, as happened
here, throw a `TypeError` before ever reaching real logic) the moment it
runs against the real database backend production actually uses.

## Fix

Not a code fix — this is expected, correct behavior difference between
the two backends, not a bug to patch around. The actual fix is procedural:
always run datetime-comparison-touching tests with `TEST_DATABASE_URL`
pointed at a real Postgres instance before considering them verified,
same habit already established for `@pytest.mark.postgres`-marked tests
elsewhere in this suite.
