"""Helper services restart on new code (runner/freshness.py, 2026-09-27)."""
import unittest

from runner.freshness import CodeWatch


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Freshness(unittest.TestCase):
    def watch(self, heads, changed=True, supervised=True):
        clock, seq = Clock(), iter(heads)
        w = CodeWatch(every=300, clock=clock, head=lambda: next(seq), changed=lambda a, b: changed,
                      supervised=lambda: supervised, root="/tmp")
        return w, clock

    def test_a_helper_exits_once_the_checkout_moves_and_its_code_changed(self):
        w, clock = self.watch(["aaa", "aaa", "bbb"])
        self.assertFalse(w.stale())                 # checked only every five minutes
        clock.t = 301
        self.assertFalse(w.stale())                 # same commit
        clock.t = 602
        self.assertTrue(w.stale())

    def test_other_changes_or_unsupervised_keep_it_running(self):
        w, clock = self.watch(["aaa", "bbb"], changed=False)
        clock.t = 301
        self.assertFalse(w.stale())                 # only UI or backend files moved
        w, clock = self.watch(["aaa", "bbb"], supervised=False)
        clock.t = 301
        self.assertFalse(w.stale())                 # a person ran it by hand: nothing restarts it
