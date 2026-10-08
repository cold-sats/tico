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


def reconcile_codex_clear(host, thread_id, event, objective):
    """A resume snapshot has no revision; verify it before stopping a new goal.

    The app server emits goal/cleared when a resumed thread has no goal, even
    though a subsequent goal/set may already have activated the requested goal.
    Query off the notification-reader thread. A failed query propagates rather
    than pretending the goal is active; a genuine clear returns a null goal.
    """
    if event.get("status") != "cleared":
        return event
    result = host.request("thread/goal/get", {"threadId": thread_id})
    goal = (result or {}).get("goal")
    if not goal:
        return event
    if goal.get("objective") != objective:
        return {**event, "status": "stopped", "note": "The native goal changed"}
    status = codex_status(goal)
    if status not in ("active", "paused", "met", "stopped"):
        raise RuntimeError("The native goal returned an unsupported status")
    return {**event, "status": status, "objective": objective,
            "note": goal.get("note") or (goal.get("status") if status == "stopped" else "")}


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
