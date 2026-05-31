from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ResendEmailTool:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def send_email(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        api_key = os.environ.get("RESEND_API_KEY", self.api_key).strip()
        if not api_key:
            return self._failure("RESEND_API_KEY is not configured.")
        sender = str(parameters.get("from", parameters.get("sender", "FRIDAY <onboarding@resend.dev>"))).strip()
        recipients = self._recipients(parameters.get("to", parameters.get("recipients", [])))
        subject = str(parameters.get("subject", "")).strip()
        html = str(parameters.get("html", "")).strip()
        text = str(parameters.get("text", "")).strip()
        confirmed = bool(parameters.get("confirmed", False))
        if not recipients:
            return self._failure("At least one valid recipient is required.")
        if not subject:
            return self._failure("Email subject is required.")
        if not html and not text:
            return self._failure("Email body is required.")
        if not confirmed:
            preview = text or self._html_preview(html)
            return {
                "success": False,
                "requires_confirmation": True,
                "message": f"Email draft ready to {', '.join(recipients)} with subject '{subject}'. Say confirm to send.",
                "data": {
                    "draft": True,
                    "from": sender,
                    "to": recipients,
                    "subject": subject,
                    "text": text,
                    "html": html,
                    "preview": preview[:600],
                },
            }
        payload: Dict[str, Any] = {"from": sender, "to": recipients, "subject": subject}
        if html:
            payload["html"] = html
        if text:
            payload["text"] = text

        request = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            return self._failure(f"Resend rejected the email: {error_body}")
        except urllib.error.URLError as exc:
            return self._failure(f"Resend is unreachable: {exc}")
        return {
            "success": True,
            "requires_confirmation": False,
            "message": "Email sent.",
            "data": {"id": data.get("id", ""), "to": recipients, "subject": subject},
        }

    def _recipients(self, value: Any) -> List[str]:
        if isinstance(value, str):
            candidates = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            candidates = [str(item).strip() for item in value]
        else:
            candidates = []
        return [email for email in candidates if EMAIL_PATTERN.match(email)]

    def _html_preview(self, html: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return " ".join(text.split())

    def _failure(self, message: str) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": {}}
