"""Keep the secrets a turn was granted out of everything the runner writes down.

A bot's credentials reach it as environment variables for one turn. Whatever the model prints, a tool echoes or a
file happens to contain must not travel on as text a model or a person reads later: the events and the reply the
runner posts to the hub, the runner's own log, the bot's repository (what is pushed) and the files it publishes.

`Redactor(values)` holds the values known for one turn and replaces each, and the common ways it turns up (URL-encoded,
base64, inside `Basic <base64>`), with `••••`. It is one precompiled pattern and a single pass, and a turn with no
secrets gets `None` from `for_turn`, so nothing runs. It fails closed: an internal error yields `[redacted: error]`
for that text, never the text.

`Redactor.scrub_tree` rewrites text files that changed in a checkout, and reports the binary ones that hold a
secret (they are left out of what is published) and whether a commit made during the turn already carries one
(then nothing is pushed).
"""
import base64
import json
import os
import stat
import uuid
import re
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote, quote_plus
from . import isolation, safe_git

MASK = "••••"
ERROR = "[redacted: error]"
MIN_LENGTH = 8
# Words that are a setting, not a secret: replacing them would only damage the text.
COMMON = {"localhost", "127.0.0.1", "production", "development", "password", "username", "enabled", "disabled",
          "undefined", "identity", "anonymous", "internal", "external", "default", "standard", "true", "false"}
_TEXT_LIMIT = 2_000_000                     # a text file bigger than this is treated as binary here

_active = {}                                # attempt id -> Redactor, for the runner's log
_lock = threading.Lock()


def _variants(value):
    """The forms one secret is written in besides itself."""
    raw = value.encode()
    forms = {value, quote(value, safe=""), quote_plus(value)}
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        text = encode(raw).decode()
        forms.update({text, text.rstrip("=")})
    return forms


def _worth(value):
    value = str(value or "")
    if len(value) < MIN_LENGTH or value.lower() in COMMON or len(set(value)) < 3:
        return False
    return True


def _values(secrets):
    """The secret values to hunt for: each one, plus the password half of `user:password`."""
    found = set()
    for value in secrets:
        value = str(value or "").strip()
        if not _worth(value):
            continue
        found.add(value)
        head, sep, tail = value.partition(":")
        if sep and "\n" not in value and _worth(tail):
            found.add(tail)
    return found


class Redactor:
    def __init__(self, secrets):
        self.update_lock = threading.Lock()
        self.values = sorted(_values(secrets), key=len, reverse=True)
        forms = set()
        for value in self.values:
            forms |= _variants(value)
        forms.discard("")
        self.pattern = re.compile("|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))) if forms else None

    def add(self, secrets):
        with self.update_lock:
            added = _values(secrets) - set(self.values)
            if not added:
                return
            updated = Redactor([*self.values, *added])
            self.values, self.pattern = updated.values, updated.pattern

    def scrub_text(self, text):
        if not isinstance(text, str) or self.pattern is None:
            return text
        try:
            return self.pattern.sub(MASK, text)
        except Exception:
            return ERROR

    def scrub_json(self, obj):
        """The same structure with every string scrubbed; keys are left as they are."""
        if isinstance(obj, str):
            return self.scrub_text(obj)
        if isinstance(obj, dict):
            return {k: self.scrub_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub_json(v) for v in obj]
        return obj

    def holds(self, data):
        """Whether these bytes carry a secret, in any of its forms."""
        if self.pattern is None:
            return False
        try:
            return self.pattern.search(data.decode("latin-1")) is not None
        except Exception:
            return True

    # ------------------------------------------------------------------ a checkout
    def scrub_files(self, paths, root=None):
        """Rewrite the text files in `paths`. (rewritten, left_out): a binary file with a secret is never touched and
        never listed as clean, so the caller can keep it out of what it publishes."""
        rewritten, left_out = [], []
        for path in map(Path, paths):
            try:
                # Anchor every parent by fd so a concurrent rename or symlink swap
                # cannot redirect either the read or the atomic replacement.
                anchored = Path(root).resolve() / path.relative_to(root) if root is not None else path.absolute()
                directory = os.open(anchored.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                temporary = None
                try:
                    for part in anchored.parts[1:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                        os.close(directory)
                        directory = child
                    try:
                        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                    except OSError:
                        if stat.S_ISLNK(os.stat(path.name, dir_fd=directory, follow_symlinks=False).st_mode):
                            continue
                        raise
                    with os.fdopen(fd, 'rb') as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        if info.st_size > _TEXT_LIMIT:
                            left_out.append(path)
                            continue
                        data = stream.read(_TEXT_LIMIT + 1)
                    if not self.holds(data):
                        continue
                    if b"\0" in data[:8000] or len(data) > _TEXT_LIMIT:
                        left_out.append(path)
                        continue
                    temporary = '.tico-scrub-' + uuid.uuid4().hex
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 stat.S_IMODE(info.st_mode), dir_fd=directory)
                    with os.fdopen(fd, 'wb') as stream:
                        os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                        stream.write(self.scrub_text(data.decode('utf-8', 'surrogateescape')).encode('utf-8', 'surrogateescape'))
                    current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        left_out.append(path)
                        continue
                    os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
                finally:
                    if temporary:
                        try:
                            os.unlink(temporary, dir_fd=directory)
                        except FileNotFoundError:
                            pass
                    os.close(directory)
                rewritten.append(path)
            except Exception:
                left_out.append(path)
        return rewritten, left_out

    def scrub_tree(self, root, since=None):
        """Scrub what a turn changed in the checkout at `root`. Returns {"rewritten": [...], "left_out": [...],
        "committed": bool}: `committed` is true when a commit made since `since` (a commit id) holds a secret."""
        result = {"rewritten": [], "left_out": [], "committed": False}
        if self.pattern is None:
            return result
        root = Path(root)
        if not (root / ".git").exists():
            return result
        changed = _git(root, "status", "--porcelain", "-z", "--untracked-files=all")
        paths = []
        for entry in (changed or "").split("\0"):
            if len(entry) > 3 and entry[:2] != " D" and entry[:2] != "D ":
                name = entry[3:]
                paths.append(root / name.split(" -> ")[-1])
        result["rewritten"], result["left_out"] = self.scrub_files(paths, root)
        if since:
            patch = _git(root, "log", "-p", "--no-ext-diff", "--no-textconv", "--format=", since + "..HEAD", raw=True)
            result["committed"] = bool(patch) and self.holds(patch)
        return result

    def register(self, attempt_id):
        with _lock:
            _active[attempt_id] = self

    def release(self, attempt_id):
        with _lock:
            _active.pop(attempt_id, None)


def for_turn(env, vault_values=(), names=("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
    """The turn's redactor, or None when it holds nothing worth hiding: the granted values, and any environment
    variable whose name says it is one."""
    secrets = list(vault_values)
    secrets.extend(v for k, v in (env or {}).items() if any(s in k.upper() for s in names))
    try:
        groups = json.loads((env or {}).get('TICO_GITHUB_TOKENS', '[]'))
        secrets.extend(group['token'] for group in groups if isinstance(group, dict) and isinstance(group.get('token'), str))
    except (ValueError, TypeError):
        pass
    redactor = Redactor(secrets)
    return redactor if redactor.pattern is not None else None


def release(attempt_id):
    with _lock:
        _active.pop(attempt_id, None)


def scrub_log(line):
    """A log line with every running turn's secrets taken out."""
    with _lock:
        active = list(_active.values())
    for redactor in active:
        line = redactor.scrub_text(line)
    return line


def head(root):
    """The checkout's current commit, or "" when it has none."""
    return (_git(Path(root), "rev-parse", "--verify", "-q", "HEAD") or "").strip()


def _git(root, *args, raw=False):
    try:
        done = isolation.run([*safe_git.prefix(root), "-C", str(root), *args],
                             env=safe_git.clean_environment(), capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return b"" if raw else ""
    if done.returncode != 0:
        return b"" if raw else ""
    return done.stdout if raw else done.stdout.decode("utf-8", "replace")
