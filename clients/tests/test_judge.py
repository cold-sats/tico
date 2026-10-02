"""The judging primitive (`clients/judge.py`): the contract, the two transports, the sets.

No network. The direct transport is exercised through its `opener` seam with a fake HTTP
response; the hub transport through a fake client. The question sets in `questions/` are
loaded for real, because a set that does not load is a broken release.
"""
import io
import json
import unittest
import urllib.error
from pathlib import Path

from clients import judge as J

ROOT = Path(__file__).resolve().parents[2]

QUESTIONS = {
    "bucket": {"type": "choice", "instructions": "Where does it go?",
               "criteria": {"archive": "noise", "reply": "answer it"}},
    "urgency": {"type": "score", "instructions": "How soon?", "criteria": ["never", "today"]},
    "is_ask": {"type": "noul", "instructions": "Is someone asking for something?"},
}
ANSWERS = {
    "bucket": {"type": "choice", "choice": "reply", "confidence": 0.8, "probabilities": {"archive": 0.2, "reply": 0.8}},
    "urgency": {"type": "score", "score": 0.7, "confidence": 0.6, "probabilities": {"0": 0.3, "1": 0.7}},
    "is_ask": {"type": "noul", "noul": 0.9},
}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status, body=b"{}"):
    return urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", status, "err", {}, io.BytesIO(body))


class Contract(unittest.TestCase):
    def test_the_shape_is_refused_before_the_network(self):
        with self.assertRaises(J.JudgeError) as caught:
            J.validate({}, {})
        self.assertEqual(caught.exception.code, "invalid")
        bad = [
            {"q": {"type": "guess", "instructions": "x"}},
            {"q": {"type": "choice", "instructions": "x", "criteria": {"only": "one"}}},
            {"q": {"type": "score", "instructions": "x", "criteria": ["one"]}},
            {"q": {"type": "noul", "instructions": ""}},
            {"q": {"type": "noul", "instructions": "x", "extra": 1}},
            {"q": {"type": "noul", "instructions": "x", "criteria": ["not", "a", "map"]}},
            {"q": {"type": "noul", "instructions": "x", "criteria": {"yes": "y", "no": "n"}}},
            {"q": {"type": "noul", "instructions": {}}},
            {"q": {"type": "noul", "instructions": 42}},
            {"q": {"type": "choice", "instructions": "x", "criteria": {"a": 1, "b": "two"}}},
            {"q": {"type": "score", "instructions": "x", "criteria": ["low", 2]}},
        ]
        for questions in bad:
            with self.assertRaises(J.JudgeError, msg=questions):
                J.validate({"a": 1}, questions)
        with self.assertRaises(J.JudgeError):
            J.validate("x" * (J.MAX_STATE_CHARS + 1), QUESTIONS)
        with self.assertRaises(J.JudgeError):
            J.validate({}, QUESTIONS, label="l" * (J.MAX_LABEL + 1))
        J.validate({"subject": "hi"}, QUESTIONS, label="mail-triage@1")


class Sets(unittest.TestCase):
    def test_registry_overrides_are_validated_and_explicit_roots_stay_authoritative(self):
        import os, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as registry:
            directory = Path(registry) / "questions"
            directory.mkdir()
            for name in ("listening-item", "mail-triage"):
                original = J.load_set(name, root=J.QUESTIONS_DIR)
                custom = {k: v for k, v in original.items() if k != "label"}
                custom["version"] += 1
                path = directory / (name + ".json")
                path.write_text(json.dumps(custom))
                with mock.patch.dict(os.environ, {"TICO_REGISTRY_DIR": registry}):
                    self.assertEqual(J.load_set(name)["label"], f"{name}@{custom['version']}")
                    self.assertEqual(J.load_set(name, root=J.QUESTIONS_DIR)["label"], original["label"])
                self.assertEqual(J.load_set(name, registry_dir=registry)["questions"], custom["questions"])
                path.write_text('{"id":"wrong"}')
                with self.assertRaises(J.JudgeError) as bad:
                    J.load_set(name, registry_dir=registry)
                self.assertEqual(bad.exception.code, "invalid")
                path.unlink()
                self.assertEqual(J.load_set(name, registry_dir=registry)["label"], original["label"])
            base = {"id": "listening-item", "version": 1, "summary": "fixture",
                    "questions": {"lead": {"type": "noul", "instructions": "A lead"}}}
            for invalid in ([], {**base, "questions": []}, {**base, "state": 3}, {**base, "questions": {
                    "lead": {"type": "choice", "dynamic": True, "instructions": "A lead", "criteria": []}}}):
                (directory / "listening-item.json").write_text(json.dumps(invalid))
                with self.assertRaises(J.JudgeError):
                    J.load_set("listening-item", registry_dir=registry)

    def test_the_triage_set_the_inbox_template_ships_is_the_release_s_own(self):
        shipped = ROOT / "templates/catalog/inbox/questions/mail-triage.json"
        self.assertEqual(shipped.read_text(), (ROOT / "questions/mail-triage.json").read_text())
        self.assertEqual(J.load_set("mail-triage", root=shipped.parent)["label"], J.load_set("mail-triage")["label"])

    def test_a_computer_without_this_checkout_s_questions_finds_the_bot_s_own_copy(self):
        import os, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as repo:
            (Path(repo) / "questions").mkdir()
            (Path(repo) / "questions/mail-triage.json").write_text((ROOT / "questions/mail-triage.json").read_text())
            with mock.patch.object(J, "QUESTIONS_DIR", Path(empty)), mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HUB_DIR", None)
                os.environ.pop("TICO_QUESTIONS_DIR", None)
                cwd = os.getcwd()
                try:
                    os.chdir(empty)
                    with self.assertRaises(J.JudgeError) as gone:
                        J.load_set("mail-triage")                  # nowhere: still the same clear refusal
                    self.assertEqual(gone.exception.code, "not_found")
                    os.chdir(repo)
                    self.assertEqual(J.load_set("mail-triage")["id"], "mail-triage")
                finally:
                    os.chdir(cwd)
                os.chdir(empty)
                try:
                    os.environ["HUB_DIR"] = repo
                    self.assertEqual(J.load_set("mail-triage")["id"], "mail-triage")
                finally:
                    os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
