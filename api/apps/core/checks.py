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


@register()
def production_file_handling(app_configs, **kwargs):
    """Outside development, uploads must be scanned by ClamAV and kept in object storage."""
    if settings.DEBUG:
        return []
    errors = []
    if settings.MALWARE_SCANNER != "clamav":
        errors.append(
            Error(
                "MALWARE_SCANNER must be 'clamav' outside development.",
                hint="The stub scanner only recognises the EICAR test file.",
                id="greenlit.E002",
            )
        )
    if settings.FILE_STORAGE_BACKEND != "s3":
        errors.append(
            Error(
                "FILE_STORAGE_BACKEND must be 's3' outside development.",
                hint="Local storage keeps files on the web server's disk.",
                id="greenlit.E003",
            )
        )
    return errors
