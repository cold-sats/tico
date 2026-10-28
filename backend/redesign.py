"""The redesign is the only design. The `redesign` team setting and its switch are gone; an install's routines and wake
rules are converted to automations once, at startup (backend/redesign_migration.py `cutover`).

`on` and `dormant` stay only while other branches still call them: `on` is always true and `dormant` adds nothing.
"""


def on(c=None):
    """Always true: the redesign is the only design."""
    return True


def dormant():
    """Route options for a redesign route: none (every route is always served)."""
    return {}
