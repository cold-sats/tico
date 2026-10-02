"""Isolate one row of background work without losing the rest of its transaction."""

import logging
from contextlib import contextmanager


@contextmanager
def isolated(c, kind, row_id, failures=None):
    c.execute("SAVEPOINT background_row")
    try:
        yield
    except Exception as exc:
        c.execute("ROLLBACK TO background_row")
        if failures is not None:
            failures.append({kind: row_id, "error": type(exc).__name__})
        logging.getLogger("tico.scheduler").exception("%s failed for %s", kind, row_id)
    finally:
        c.execute("RELEASE background_row")
