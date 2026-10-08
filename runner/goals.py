"""Native harness capability checks and the shared goal event vocabulary."""
import functools
import re
import subprocess
import tempfile
from pathlib import Path


def command(name, help, args=""):
    return {"name": name, "args": args, "help": help, "kind": "harness"}


# The server keeps at most this many commands per bot (backend/models.py, GoalReadiness).
MAX_COMMANDS = 30
REPO_COMMAND_NAME = re.compile(r"^[a-z0-9][a-z0-9_:-]{0,63}$")
_FRONTMATTER = {}     # (path, mtime_ns, size) -> parsed fields: readiness runs every heartbeat, files rarely change


def frontmatter(path):
    """The leading `---` block's plain `key: value` fields; folded and literal values become one line."""
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key in _FRONTMATTER:
            return _FRONTMATTER[key]
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(8192)
    except OSError:
        return {}
    fields, lines = {}, head.splitlines()
    if lines and lines[0].strip() == "---":
        name = None
        for line in lines[1:]:
            if line.strip() == "---":
                break
            match = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
            if match:
                name, value = match.group(1).lower(), match.group(2).strip()
                fields[name] = "" if value in (">", "|", ">-", "|-") else value.strip("'\"")
            elif name and line[:1] in (" ", "\t"):
                fields[name] = (fields[name] + " " + line.strip()).strip()
    if len(_FRONTMATTER) > 2000:
        _FRONTMATTER.clear()
    _FRONTMATTER[key] = fields
    return fields


def repo_commands(root):
    """A Claude Code bot's own skills and commands, from its repository's .claude folder.

    Claude Code runs these as "/name" in `claude -p`, so they go to the harness as-is, like /compact.
    Skills marked `user-invocable: false` are the model's alone. A command in a subfolder keeps its file name.
    """
    found, root = [], Path(root)
    skills = root / ".claude" / "skills"
    try:
        folders = sorted(path for path in skills.iterdir() if path.is_dir()) if skills.is_dir() else []
    except OSError:
        folders = []
    for folder in folders[:MAX_COMMANDS * 2]:
        fields = frontmatter(folder / "SKILL.md")
        if fields and fields.get("user-invocable", "").lower() != "false":
            found.append((fields.get("name") or folder.name, fields))
    commands = root / ".claude" / "commands"
    try:
        files = sorted(commands.glob("*.md")) + sorted(commands.glob("*/*.md")) if commands.is_dir() else []
    except OSError:
        files = []
    for path in files[:MAX_COMMANDS * 2]:
        fields = frontmatter(path)
        if path.is_file():
            found.append((path.stem, fields))
    result = []
    for name, fields in found:
        name = name.strip().lower()
        if not REPO_COMMAND_NAME.match(name):
            continue
        help = " ".join(fields.get("description", "").split())
        help = help if len(help) <= 80 else help[:79].rstrip() + "…"
        result.append(command(name, help, fields.get("argument-hint", "")[:100]))
    return result


def with_repo_commands(builtins, root):
    """The harness's own commands first, then the repository's, without repeating a name."""
    merged, seen = list(builtins), {item["name"] for item in builtins}
    for item in repo_commands(root):
        if item["name"] not in seen and len(merged) < MAX_COMMANDS:
            seen.add(item["name"])
            merged.append(item)
    return merged


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
