"""The judging primitive (`clients/judge.py`): the contract, the two transports, the sets.

No network. The direct transport is exercised through its `opener` seam with a fake HTTP
response; the hub transport through a fake client. The question sets in `questions/` are
loaded for real, because a set that does not load is a broken release.
"""
import io
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


if __name__ == "__main__":
    unittest.main()
