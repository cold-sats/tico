"""Unsubscribe eligibility, network boundary and retry safety; no real mail or network."""
import sqlite3
import sys
import unittest
from unittest.mock import patch, MagicMock

from connectors.mail import unsubscribe as u, access, Refused

RAW = b'''From: Newsletter <news@example.org>\r
List-Unsubscribe: <https://example.org/unsub?token=private>\r
List-Unsubscribe-Post: List-Unsubscribe=One-Click\r
DKIM-Signature: v=1; h=from:list-unsubscribe:list-unsubscribe-post; b=fake\r
\r
Newsletter\r
'''


class Unsubscribe(unittest.TestCase):
    def test_reject_private_and_mixed_dns(self):
        for ips in [['127.0.0.1'], ['169.254.169.254'], ['::1'], ['8.8.8.8', '10.0.0.1']]:
            rows = [(2, 1, 6, '', (ip, 443)) for ip in ips]
            with patch.object(u.socket, 'getaddrinfo', return_value=rows):
                with self.assertRaises(u.Unsupported):
                    u.public_address('example.org')

class RulesPipeline(unittest.TestCase):
    def test_protected_mail_never_unsubscribes(self):
        from connectors.mail import rules
        rs = [{'id': 'protect', 'when': {}, 'do': {'never_archive': True}},
              {'id': 'subscription', 'when': {}, 'do': {'unsubscribe': True, 'archive': True}}]
        plan = rules.apply(rs, {})
        self.assertFalse(plan['unsubscribe'])
        self.assertFalse(plan['archive'])
