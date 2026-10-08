"""allauth hooks: lockout email, provider bookkeeping, and encrypted TOTP secrets (M1-07)."""

import base64
import hashlib

from allauth.account.adapter import DefaultAccountAdapter
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail

from apps.core.models import User

LOCKOUT_WINDOW_SECONDS = 15 * 60
LOCKOUT_THRESHOLD = 5


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


class AccountAdapter(DefaultAccountAdapter):
    def authentication_failed(self, request, **credentials) -> None:
        """Count failures per address; email the account holder when it reaches the limit.

        allauth already slows the account and the IP (`ACCOUNT_RATE_LIMITS["login_failed"]`).
        This adds the warning email (SEC §3), sent once per window and only to a real account,
        so the response never reveals whether an address is registered.
        """
        email = (credentials.get("email") or credentials.get("username") or "").strip().lower()
        if not email:
            return
        key = _email_key(email)
        count_key = f"login-failures:{key}"
        cache.add(count_key, 0, LOCKOUT_WINDOW_SECONDS)
        try:
            count = cache.incr(count_key)
        except ValueError:  # expired between add and incr
            cache.set(count_key, 1, LOCKOUT_WINDOW_SECONDS)
            count = 1
        if count >= LOCKOUT_THRESHOLD and cache.add(
            f"login-alert:{key}", 1, LOCKOUT_WINDOW_SECONDS
        ):
            if User.objects.filter(email__iexact=email, is_active=True).exists():
                send_mail(
                    "Someone is trying to sign in to your Greenlit account",
                    "There were several failed sign-in attempts on your account in the last "
                    "15 minutes, so further attempts are being slowed down.\n\n"
                    "If this was you, wait a few minutes and try again, or reset your password. "
                    "If it was not you, no action is needed, but you may want to set up "
                    "two-step verification.",
                    None,
                    [email],
                )


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.auth_provider = sociallogin.account.provider
        name = " ".join(filter(None, [data.get("first_name"), data.get("last_name")])).strip()
        if name and not getattr(user, "name", ""):
            user.name = name[:200]
        return user


def _fernet() -> MultiFernet:
    """Keys from FIELD_ENCRYPTION_KEYS (comma-separated; the first encrypts, all decrypt).

    Without keys (local development and tests) one is derived from SECRET_KEY. Production
    refuses to start without real keys (config/settings/production.py).
    """
    keys = [k.strip() for k in settings.FIELD_ENCRYPTION_KEYS if k.strip()]
    if not keys:
        derived = hashlib.sha256(f"greenlit-field-encryption:{settings.SECRET_KEY}".encode())
        keys = [base64.urlsafe_b64encode(derived.digest()).decode()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


class MFAAdapter(DefaultMFAAdapter):
    """allauth stores the TOTP secret in the clear by default; encrypt it at rest (SEC §6)."""

    def encrypt(self, text: str) -> str:
        return _fernet().encrypt(text.encode()).decode()

    def decrypt(self, encrypted_text: str) -> str:
        return _fernet().decrypt(encrypted_text.encode()).decode()
