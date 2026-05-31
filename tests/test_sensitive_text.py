from __future__ import annotations

import unittest

from friday.control.sensitive_text import (
    contains_sensitive_text,
    contains_visual_sensitive_text,
    redact_phone_number,
    redact_sensitive_text,
)


class ContainsSensitiveTextTests(unittest.TestCase):
    def test_password_match(self) -> None:
        self.assertTrue(contains_sensitive_text("Enter your password please"))

    def test_2fa_match(self) -> None:
        self.assertTrue(contains_sensitive_text("Send the 2FA code"))

    def test_clean_text(self) -> None:
        self.assertFalse(contains_sensitive_text("Hello there"))


class ContainsVisualSensitiveTextTests(unittest.TestCase):
    def test_captcha_match(self) -> None:
        self.assertTrue(contains_visual_sensitive_text("Solve this captcha first"))

    def test_security_question_match(self) -> None:
        self.assertTrue(contains_visual_sensitive_text("Answer your security question"))


class RedactPhoneNumberTests(unittest.TestCase):
    def test_e164(self) -> None:
        self.assertEqual(redact_phone_number("+15551234567"), "***-***-4567")

    def test_nanp_with_dashes(self) -> None:
        self.assertEqual(redact_phone_number("555-123-4567"), "***-***-4567")

    def test_nanp_with_parens(self) -> None:
        self.assertEqual(redact_phone_number("(555) 123-4567"), "***-***-4567")

    def test_short_number_fully_masked(self) -> None:
        self.assertEqual(redact_phone_number("12"), "***-***-****")

    def test_empty_string(self) -> None:
        self.assertEqual(redact_phone_number(""), "***-***-****")

    def test_non_string_returns_placeholder(self) -> None:
        # type: ignore[arg-type]
        self.assertEqual(redact_phone_number(None), "***-***-****")  # type: ignore[arg-type]


class RedactSensitiveTextTests(unittest.TestCase):
    def test_redacts_email(self) -> None:
        self.assertIn("[REDACTED_EMAIL]", redact_sensitive_text("Reach me at user@example.com please"))

    def test_redacts_phone_number_in_running_text(self) -> None:
        clean = redact_sensitive_text("My number is +1 555 123 4567")
        self.assertIn("***-***-4567", clean)
        self.assertNotIn("555", clean)

    def test_redacts_labeled_password(self) -> None:
        clean = redact_sensitive_text("password=hunter2 should never leak")
        self.assertIn("[REDACTED]", clean)
        self.assertNotIn("hunter2", clean)

    def test_preserves_plain_text(self) -> None:
        self.assertEqual(redact_sensitive_text("just a normal sentence"), "just a normal sentence")


if __name__ == "__main__":
    unittest.main()
