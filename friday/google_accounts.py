from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


GOOGLE_ACCOUNT_HOSTS = {
    "accounts.google.com",
    "calendar.google.com",
    "classroom.google.com",
    "docs.google.com",
    "docs.new",
    "drive.google.com",
    "gemini.google.com",
    "mail.google.com",
    "myaccount.google.com",
    "sheets.google.com",
    "slides.google.com",
    "slides.new",
}


def personal_google_account() -> str:
    return (
        os.environ.get("FRIDAY_PERSONAL_GOOGLE_ACCOUNT")
        or os.environ.get("FRIDAY_GOOGLE_ACCOUNT")
        or ""
    ).strip()


def classroom_google_account() -> str:
    return (
        os.environ.get("FRIDAY_CLASSROOM_ACCOUNT")
        or personal_google_account()
        or ""
    ).strip()


def is_google_account_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    return host in GOOGLE_ACCOUNT_HOSTS


def with_authuser(url: str, account: str) -> str:
    clean_url = url.strip()
    clean_account = account.strip()
    if not clean_account or not is_google_account_url(clean_url):
        return clean_url
    parsed = urlparse(clean_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("authuser", clean_account)
    return urlunparse(parsed._replace(query=urlencode(query)))


def account_chooser_url(url: str, account: str) -> str:
    clean_url = with_authuser(url, account)
    clean_account = account.strip()
    if not clean_account or not is_google_account_url(clean_url):
        return clean_url
    if urlparse(clean_url).netloc.lower().removeprefix("www.") == "accounts.google.com":
        return clean_url
    return "https://accounts.google.com/AccountChooser?" + urlencode(
        {"Email": clean_account, "continue": clean_url}
    )


def preferred_google_url(url: str, account: str | None = None) -> str:
    clean_account = personal_google_account() if account is None else account.strip()
    return account_chooser_url(url, clean_account)
