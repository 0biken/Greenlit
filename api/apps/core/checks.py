from django.conf import settings
from django.core.checks import Error, register


@register()
def field_encryption_keys_set(app_configs, **kwargs):
    """Outside development, TOTP secrets must be encrypted with a real key, not one derived from
    SECRET_KEY (apps/core/auth_adapter.py)."""
    if not settings.DEBUG and not any(k.strip() for k in settings.FIELD_ENCRYPTION_KEYS):
        return [
            Error(
                "FIELD_ENCRYPTION_KEYS is not set.",
                hint='Generate one with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"',
                id="greenlit.E001",
            )
        ]
    return []
