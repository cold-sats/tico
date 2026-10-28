"""The redesign scenarios, by PLAN §7 group: task caps (1-10), spend (11-15), inboxes (16-21), engine (22-31),
permissions (32-35), redesign off (45). The coverage matrix is not listed here: run.py builds it per seed."""
from .caps import SCENARIOS as _caps
from .engine import SCENARIOS as _engine
from .inboxes import SCENARIOS as _inboxes
from .permissions import SCENARIOS as _permissions
from .setting import SCENARIOS as _setting
from .spend import SCENARIOS as _spend

SCENARIOS = _caps + _spend + _inboxes + _engine + _permissions + _setting
