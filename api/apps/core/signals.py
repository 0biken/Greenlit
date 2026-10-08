import time

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def remember_login_time(sender, request, user, **kwargs) -> None:
    """Stamp the session at sign-in, so it can be ended after the 30-day maximum (SEC §3)."""
    if request is not None and hasattr(request, "session"):
        request.session["login_at"] = int(time.time())
