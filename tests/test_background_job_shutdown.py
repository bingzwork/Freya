import time

from app.core.background_jobs import BackgroundJobService


def test_shutdown_interrupts_scheduler_wait_within_budget():
    service = BackgroundJobService(tick_interval=30.0)
    service.start()
    started = time.monotonic()
    service.shutdown(timeout=2.0)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0
    assert service.is_running() is False
    assert not service._scheduler_thread.is_alive()
