"""Password rules beyond length (SEC §3: checked against a known-breached list)."""

import hashlib

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
TIMEOUT_SECONDS = 2


class BreachedPasswordValidator:
    """Refuse a password that appears in a known data breach.

    Uses the Pwned Passwords range API: only the first 5 characters of the password's SHA-1 hash
    leave the server, and the match is made here. If the service is slow, down, or returns
    something unexpected, the check is skipped, so sign-up never depends on a third party.
    Switch it off with BREACHED_PASSWORD_CHECK = False (local development and tests).
    """

    def validate(self, password: str, user=None) -> None:
        if not getattr(settings, "BREACHED_PASSWORD_CHECK", True):
            return
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()  # noqa: S324
        prefix, suffix = digest[:5], digest[5:]
        try:
            response = requests.get(
                RANGE_URL.format(prefix=prefix),
                headers={"Add-Padding": "true", "User-Agent": "Greenlit"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            lines = response.text.splitlines()
        except requests.RequestException:
            return  # fail open
        for line in lines:
            candidate, _, count = line.partition(":")
            # Padding entries come back with a count of 0 and are not real matches.
            if candidate.strip().upper() == suffix and count.strip().isdigit() and int(count) > 0:
                raise ValidationError(
                    "This password has appeared in a data breach. Choose a different one.",
                    code="password_breached",
                )

    def get_help_text(self) -> str:
        return "Your password must not have appeared in a known data breach."
