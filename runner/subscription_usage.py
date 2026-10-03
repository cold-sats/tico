"""Non-secret weekly allowance snapshots, scoped to a local profile and runtime."""
import math
import threading
from datetime import datetime, timezone

class Reports:
    def __init__(self):
        self._lock = threading.Lock()
        self._reports = {}

    def remember(self, profile, runtime, event):
        if not profile or runtime not in ("codex", "claude") or event.get("window_minutes") != 10080:
            return
        percent = event.get("used_percent")
        if percent is not None and (isinstance(percent, bool) or not isinstance(percent, (int, float))
                                    or not math.isfinite(percent) or not 0 <= percent <= 100):
            return
        reset = event.get("resets_at")
        if reset:
            try:
                stamp = datetime.fromisoformat(reset.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    return
                reset = stamp.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, AttributeError):
                return
        with self._lock:
            self._reports[profile, runtime] = {"used_percent": percent, "resets_at": reset,
                "reported_at": datetime.now(timezone.utc).isoformat(),
                "status": event.get("status") if event.get("status") in ("allowed", "allowed_warning", "rejected") else None}


    def attach(self, rows):
        # Never mutate the cached sign-in report. No credentials, account IDs or paths leave the computer.
        with self._lock:
            return [{**p, "runtimes": {runtime: {**state, **({"weekly": dict(self._reports[p["name"], runtime])}
                        if (p["name"], runtime) in self._reports else {})}
                    for runtime, state in p["runtimes"].items()}} for p in rows]
