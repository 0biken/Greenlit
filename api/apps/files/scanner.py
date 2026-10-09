"""Malware scanning before a file is made available (SEC §8).

`MALWARE_SCANNER = "clamav"` talks to a ClamAV daemon (CLAMAV_HOST, CLAMAV_PORT). `"stub"` is for
development and tests only: it flags the standard EICAR test file and `TEST_MARKER`, so the
infected path can be exercised without ClamAV. Outside development the project refuses to start
with the stub (check greenlit.E002).
"""

from typing import IO

from django.conf import settings

# The industry-standard harmless test signature every scanner reports as infected.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
# Desktop antivirus quarantines EICAR as soon as it touches disk, which stops a test before
# Greenlit's own handling runs. The stub also treats this marker as infected; nothing else does.
TEST_MARKER = b"GREENLIT-TEST-MALWARE-SIGNATURE"


class ScannerUnavailable(Exception):
    """The scanner could not be reached; the job retries."""


def is_infected(file: IO[bytes]) -> bool:
    file.seek(0)
    try:
        if settings.MALWARE_SCANNER == "stub":
            content = file.read()
            return EICAR in content or TEST_MARKER in content
        if settings.MALWARE_SCANNER == "clamav":
            return _clamav(file)
        raise ValueError(f"Unknown MALWARE_SCANNER {settings.MALWARE_SCANNER!r}")
    finally:
        file.seek(0)


def _clamav(file: IO[bytes]) -> bool:
    import clamd

    try:
        client = clamd.ClamdNetworkSocket(
            host=settings.CLAMAV_HOST, port=settings.CLAMAV_PORT, timeout=60
        )
        result = client.instream(file)
    except (clamd.ConnectionError, OSError) as exc:
        raise ScannerUnavailable("ClamAV is not reachable") from exc
    status, _signature = result.get("stream", ("ERROR", None))
    if status == "FOUND":
        return True
    if status == "OK":
        return False
    raise ScannerUnavailable(f"ClamAV answered {status}")
