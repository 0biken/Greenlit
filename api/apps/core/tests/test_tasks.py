from apps.core.tasks import ping


def test_ping_runs_inline_in_local_settings():
    # Local settings run jobs eagerly, so no Redis or worker is needed.
    assert ping.delay().get() == "pong"
