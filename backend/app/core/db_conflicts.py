"""Classification shared by retryable PostgreSQL transaction owners."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError

# Postgres SQLSTATEs that mean "this transaction lost a race, run it again":
# serialization_failure, deadlock_detected, and lock_not_available.
_TRANSIENT_DB_SQLSTATES = frozenset({"40001", "40P01", "55P03"})


def is_transient_db_conflict(exc: BaseException) -> bool:
    """Return whether PostgreSQL aborted the transaction for lock contention."""
    coded = False
    for error in (exc, getattr(exc, "orig", None), getattr(exc, "__cause__", None)):
        if error is None:
            continue
        code = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
        if code is None:
            continue
        coded = True
        if code in _TRANSIENT_DB_SQLSTATES:
            return True
    if coded:
        return False
    return isinstance(exc, DBAPIError) and any(
        token in str(exc)
        for token in (
            "deadlock detected",
            "could not serialize",
            "canceling statement due to lock timeout",
        )
    )
