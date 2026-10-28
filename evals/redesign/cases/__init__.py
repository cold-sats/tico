"""The redesign scenarios, by PLAN §7 group: task caps (1-10), spend (11-15), permissions (32-35), redesign off (45)."""
from .caps import SCENARIOS as _caps
from .permissions import SCENARIOS as _permissions
from .setting import SCENARIOS as _setting
from .spend import SCENARIOS as _spend

SCENARIOS = _caps + _spend + _permissions + _setting
