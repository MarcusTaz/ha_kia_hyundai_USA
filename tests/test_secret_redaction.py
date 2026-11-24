"""Secrets must not reach debug logs or the diagnostics download."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

import test_genesis_polling  # noqa: F401  (loads the API package without Home Assistant)

COMPONENT_ROOT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "ha_kia_hyundai"
)
clean = sys.modules["ha_kia_hyundai.kia_hyundai_api.util"].clean_dictionary_for_logging


class LogMaskingTests(unittest.TestCase):
    def test_bluelink_login_reply_tokens_are_masked(self):
        cleaned = clean({
            "access_token": "secret-access",
            "refresh_token": "secret-refresh",
            "expires_in": "1799",
            "username": "user@example.com",
        })

        self.assertEqual(cleaned["access_token"], "***")
        self.assertEqual(cleaned["refresh_token"], "***")
        self.assertEqual(cleaned["username"], "***")
        self.assertEqual(cleaned["expires_in"], "1799")

    def test_pin_and_access_token_headers_are_masked_in_any_case(self):
        cleaned = clean({
            "blueLinkServicePin": "1234",
            "bluelinkservicepin": "1234",
            "accessToken": "secret-access",
            "gen": "2",
        })

        self.assertEqual(cleaned["blueLinkServicePin"], "***")
        self.assertEqual(cleaned["bluelinkservicepin"], "***")
        self.assertEqual(cleaned["accessToken"], "***")
        self.assertEqual(cleaned["gen"], "2")

    def test_kia_session_headers_are_masked(self):
        cleaned = clean({"sid": "secret-sid", "rmtoken": "secret-rm", "otpkey": "secret-otp"})

        self.assertEqual(set(cleaned.values()), {"***"})

    def test_nested_values_are_masked(self):
        cleaned = clean({"payload": {"items": [{"access_token": "secret-access"}]}})

        self.assertEqual(cleaned["payload"]["items"][0]["access_token"], "***")


class DiagnosticsRedactionTests(unittest.TestCase):
    """diagnostics.py needs Home Assistant to import, so read its source."""

    def test_config_entry_secrets_are_in_the_redaction_set(self):
        tree = ast.parse((COMPONENT_ROOT / "diagnostics.py").read_text())
        redacted: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "TO_REDACT" for t in node.targets)
            ):
                redacted = {getattr(e, "id", getattr(e, "value", "")) for e in node.value.elts}

        for name in ("CONF_PASSWORD", "CONF_PIN", "CONF_REFRESH_TOKEN", "CONF_DEVICE_ID"):
            self.assertIn(name, redacted)


if __name__ == "__main__":
    unittest.main()
