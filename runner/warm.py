"""Bounded, per-conversation harness cache with revocable per-turn credentials."""
import hashlib
import json
import os
import threading
import time

from . import isolation


class WarmSessions:
    def __init__(self, directory, limit=8, idle_seconds=900):
        self.directory = directory
        self.limit, self.idle_seconds = limit, idle_seconds
        self.entries = {}
        self.lock = threading.RLock()

    @staticmethod
    def scope(attempt):
        return hashlib.sha256(json.dumps([
            attempt["bot"], attempt["conversation"]["id"], attempt.get("principal"),
            attempt.get("session_epoch", 0), attempt["config"].get("model"),
            attempt["config"].get("reasoning_effort"), attempt["config"].get("harness"),
        ]).encode()).hexdigest()

    @staticmethod
    def write_token(path, token):
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(token)
        os.replace(tmp, path)
        isolation.chown(path)

    def acquire(self, attempt, env, factory):
        key = self.scope(attempt)
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in env.items() if k != "HUB_TOKEN"}, sort_keys=True).encode()).hexdigest()
        with self.lock:
            self.prune()
            entry = self.entries.get(key)
            if entry and entry["busy"]:
                raise RuntimeError("Conversation already has an active turn")
            if entry and (entry["fingerprint"] != fingerprint or not entry["host"].alive()):
                entry["host"].stop()
                del self.entries[key]
                entry = None
            home = self.directory / key
            isolation.mkdir(home)
            os.chmod(home, 0o700)
            token_file = home / "lease-token"
            token = env["HUB_TOKEN"]
            env = {**env, "HUB_TOKEN": "tico-file:" + str(token_file)}
            if entry is None:
                entry = {"host": factory(attempt, env), "fingerprint": fingerprint,
                         "token_file": token_file, "busy": False, "used": time.monotonic()}
                self.entries[key] = entry
            self.write_token(token_file, token)
            entry["busy"] = True
            return entry["host"], env

    def release(self, host, success):
        with self.lock:
            for key, entry in list(self.entries.items()):
                if entry["host"] is host:
                    self.write_token(entry["token_file"], "")
                    entry.update(busy=False, used=time.monotonic())
                    if not success or not host.alive():
                        host.stop()
                        del self.entries[key]
                    return

    def prune(self, close=False):
        with self.lock:
            idle = sorted(((key, e) for key, e in self.entries.items() if not e["busy"]), key=lambda item: item[1]["used"])
            for key, entry in idle:
                if close or len(self.entries) >= self.limit or time.monotonic() - entry["used"] > self.idle_seconds:
                    self.write_token(entry["token_file"], "")
                    entry["host"].stop()
                    del self.entries[key]

    def close_runtime(self, name):
        """Stop every idle process of one host, before its executable is replaced on disk."""
        with self.lock:
            for key, entry in list(self.entries.items()):
                if not entry["busy"] and getattr(entry["host"], "name", "") == name:
                    self.write_token(entry["token_file"], "")
                    entry["host"].stop()
                    del self.entries[key]
