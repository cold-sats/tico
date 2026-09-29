"""Preflight (clients/preflight.py) over a repo built in a temp folder: no git remote, no model, no mail."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clients import preflight as PF


def lines(fn, *args):
    r = PF.Report("t")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = fn(r, *args)
    return r, out.getvalue().splitlines(), result


class Manifest(unittest.TestCase):
    def test_a_manifest_that_names_another_employee_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "employee.yaml").write_text("name: someone-else\n")
            r, out, m = lines(PF.check_manifest, "seo", d)
        self.assertEqual(m, {"name": "someone-else"})
        self.assertEqual(r.counts["FAIL"], 1)
        self.assertTrue(any("expected 'seo'" in l for l in out))

class Schedules(unittest.TestCase):
    def test_routines_are_validated_the_way_the_runner_validates_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "playbooks").mkdir()
            (d / "playbooks/weekly.md").write_text("Do the weekly review.\n")
            m = {"schedules": [{"cron": "0 8 * * 1", "title": "Weekly review", "template": "playbooks/weekly.md"}]}
            r, out, _ = lines(PF.check_schedules, d, m)
        self.assertEqual(r.counts, {"PASS": 2, "WARN": 0, "FAIL": 0})
        self.assertTrue(any("America/Los_Angeles" in l for l in out))

if __name__ == "__main__":
    unittest.main(verbosity=2)
