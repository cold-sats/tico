"""The HTTP client's retry rule (clients/tico.py): 429 and every 5xx retry, the rest do not."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from clients.tico import APIError, Client

CLOUDFLARE_530 = {"type": "about:blank", "title": "Error 1033: Cloudflare Tunnel error", "status": 530,
                  "detail": "The host is unreachable", "retryable": False}


class _Opener:
    """Answers each open() from a script of HTTP statuses (with a JSON body) or dict replies."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def open(self, req, timeout=None):
        self.calls.append(req)
        step = self.script.pop(0)
        if isinstance(step, dict):
            return _Response(step)
        code, body = step
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(json.dumps(body).encode()))


class _Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Retries(unittest.TestCase):
    def client(self, script, retries=2):
        client = Client("https://runner.example", "tok", retries=retries)
        client.opener = _Opener(script)
        return client

    def test_a_cloudflare_530_is_retried_and_keeps_its_title(self):
        client = self.client([(502, {}), (530, CLOUDFLARE_530), (530, CLOUDFLARE_530)])
        with mock.patch("clients.tico.time.sleep") as sleep, self.assertRaises(APIError) as caught:
            client.post("jobs/claim", {})
        self.assertEqual(len(client.opener.calls), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.status, 530)
        self.assertEqual(caught.exception.code, "http_error")
        self.assertEqual(caught.exception.detail, "HTTP 530: Error 1033: Cloudflare Tunnel error")
        # Every attempt of one request carries the same idempotency key.
        self.assertEqual({r.get_header("Idempotency-key") for r in client.opener.calls}, {caught.exception.operation_id})

    def test_a_404_is_not_retried(self):
        client = self.client([(404, {"error": {"code": "not_found", "detail": "No such attempt"}})])
        with mock.patch("clients.tico.time.sleep") as sleep, self.assertRaises(APIError) as caught:
            client.post("attempts/x/renew", {})
        self.assertEqual(len(client.opener.calls), 1)
        self.assertFalse(sleep.called)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("not_found", "No such attempt"))

if __name__ == "__main__":
    unittest.main()


class PlainHttpTests(unittest.TestCase):
    def test_loopback_and_service_names_may_use_http(self):
        for url in ("http://127.0.0.1:8765", "http://localhost:8765", "http://server:8765", "http://[::1]:8765",
                    "https://tico.example.com"):
            Client(url, "t")

    def test_everything_else_needs_https(self):
        for url in ("http://tico.example.com", "http://8.8.8.8:8765", "http://169.254.169.254", "http://10.0.3.4:8765",
                    "http://192.168.1.20", "http://server.example", "http://127.0.0.1.evil.example",
                    "http://[fe80::1]:8765"):
            with self.assertRaises(ValueError, msg=url):
                Client(url, "t")
