"""Named seeds for the real-hub browser server (ui/tests/support/real_hub_server.py, --seed). A seed takes the world the
server runs (harness.Org) and makes one piece of state a browser test starts from, through the API a teammate calls.
Seeds run in the order given. A seed returns False when it skipped itself because the route it needs is not built yet;
otherwise it returns None."""
from .harness import Unmet

SEEDS = {}


def seed(name):
    def register(fn):
        SEEDS[name] = fn
        return fn
    return register


@seed("org")
def org(world):
    """The scenario org: its people, bots and reports_to are built when the world starts, so nothing is added here."""


@seed("redesign_on")
def redesign_on(world):
    """The redesign setting on, through PUT /api/v2/settings/redesign as Chris. Skipped until the route exists."""
    try:
        reply = world.redesign_on()
    except Unmet:
        return False
    if not 200 <= reply.status < 300:
        raise RuntimeError(f"redesign setting: {reply.status} {reply.excerpt()}")
