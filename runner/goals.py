"""Native harness capability checks and the shared goal event vocabulary."""
import functools
import re
import subprocess
import tempfile
from pathlib import Path


def command(name, help, args=""):
    return {"name": name, "args": args, "help": help, "kind": "harness"}


@functools.lru_cache(maxsize=32)
def capabilities(runtime, executable, version):
    if not executable:
        return {"goals": False, "commands": []}
    supported = False
    commands = []
    if runtime == "claude":
        match = re.search("(\\d+)\\.(\\d+)\\.(\\d+)", version)
        supported = bool(match and tuple(map(int, match.groups())) >= (2, 1, 212))
        if supported:
            commands = [command("compact", "Compact this conversation", "[instructions]"),
                        command("clear", "Clear the harness conversation"),
                        command("model", "Change the harness model", "[model]")]
    elif runtime == "codex":
        # The installed protocol, rather than a version guess, determines native goal support.
        try:
            with tempfile.TemporaryDirectory(prefix="tico-goal-schema-") as directory:
                result = subprocess.run([executable, "app-server", "generate-json-schema", "--experimental",
                                         "--out", directory], capture_output=True, timeout=10)
                if result.returncode == 0:
                    schema = Path(directory) / "v2"
                    supported = (schema / "ThreadGoalSetParams.json").exists()
                    if (schema / "ThreadCompactStartParams.json").exists():
                        commands.append(command("compact", "Compact this conversation"))
                    if (schema / "ReviewStartParams.json").exists():
                        commands.append(command("review", "Review changes", "[instructions]"))
        except (OSError, subprocess.SubprocessError):
            pass
    return {"goals": supported, "commands": commands}


def codex_status(goal):
    status = goal.get("status")
    return {"complete": "met", "blocked": "stopped", "usageLimited": "stopped",
            "budgetLimited": "stopped", "budget_limited": "stopped", "completed": "met"}.get(status, status)


def claude_status(message):
    attachment = message.get("attachment") or message
    if attachment.get("type") != "goal_status":
        return None
    status = ("stopped" if attachment.get("failed") else "met" if attachment.get("met") else
              "cleared" if attachment.get("sentinel") else "active")
    # A false sentinel marks goal creation; a true sentinel marks an explicit clear.
    if attachment.get("sentinel"):
        status = "cleared" if attachment.get("met") else "active"
    return {"status": status, "note": attachment.get("reason") or "",
            "objective": attachment.get("condition")}
