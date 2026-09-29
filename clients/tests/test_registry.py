"""The registry merge and the small rules that hang off an entry (clients/registry.py)."""
import tempfile
import unittest
from pathlib import Path

from clients import registry as REG

EMP = {"name": "seo", "runtime": "codex", "model": "gpt-6-sol", "reasoning_effort": "high"}


class Merge(unittest.TestCase):
    def test_the_seed_registry_loads(self):
        defaults, entries = REG.load_registry(REG.HUB_DIR / "templates/environment-registry/employees.yaml")
        # The seed names no vendor: the runtime and model come from the company's provider choice.
        self.assertNotIn("runtime", defaults)
        self.assertNotIn("model", defaults)
        self.assertTrue(any(e["name"] == "coo" for e in entries))


if __name__ == "__main__":
    unittest.main(verbosity=2)
