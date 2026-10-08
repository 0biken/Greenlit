import uuid

import pytest


@pytest.fixture
def real_cache(settings):
    """A working cache for tests of lockouts and limits; the suite's default stores nothing."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"security-{uuid.uuid4()}",
        }
    }
