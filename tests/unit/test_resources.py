from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.core.errors import OperationBusyError, OperationTimeoutError
from app.core.resources import OperationCapacity


def test_operation_capacity_enforces_timeout_and_recovers_slot() -> None:
    release = Event()
    late_complete = Event()
    capacity = OperationCapacity(operation="conversion", capacity=1, queue_timeout=0)

    with pytest.raises(OperationTimeoutError):
        capacity.run(
            lambda: release.wait(1),
            timeout=0.01,
            on_late_complete=late_complete.set,
        )
    release.set()
    assert late_complete.wait(1)
    assert capacity.run(lambda: "ready", timeout=1) == "ready"
    capacity.shutdown()


def test_operation_capacity_rejects_when_all_slots_are_busy() -> None:
    started = Event()
    release = Event()
    capacity = OperationCapacity(operation="conversion", capacity=1, queue_timeout=0)

    def blocking_operation() -> bool:
        started.set()
        return release.wait(1)

    with ThreadPoolExecutor(max_workers=1) as caller:
        running = caller.submit(capacity.run, blocking_operation, timeout=1)
        assert started.wait(1)
        with pytest.raises(OperationBusyError):
            capacity.run(lambda: None, timeout=1)
        release.set()
        assert running.result(timeout=1) is True
    capacity.shutdown()
