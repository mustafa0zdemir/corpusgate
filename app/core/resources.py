from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from threading import BoundedSemaphore
from typing import TypeVar

from app.core.errors import OperationBusyError, OperationTimeoutError

ResultT = TypeVar("ResultT")


class OperationCapacity:
    """Bound expensive synchronous work and enforce a caller-visible deadline."""

    def __init__(self, *, operation: str, capacity: int, queue_timeout: int):
        self.operation = operation
        self.queue_timeout = queue_timeout
        self._semaphore = BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(
            max_workers=capacity,
            thread_name_prefix=f"corpusgate-{operation}",
        )

    def run(
        self,
        function: Callable[[], ResultT],
        *,
        timeout: int,
        on_late_complete: Callable[[], None] | None = None,
    ) -> ResultT:
        if not self._semaphore.acquire(timeout=self.queue_timeout):
            raise OperationBusyError(self.operation)

        future: Future[ResultT] = self._executor.submit(function)
        release_in_callback = False
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            release_in_callback = True
            future.add_done_callback(
                lambda _future: self._complete_late_operation(on_late_complete)
            )
            raise OperationTimeoutError(self.operation) from exc
        finally:
            if not release_in_callback:
                self._semaphore.release()

    def _complete_late_operation(self, callback: Callable[[], None] | None) -> None:
        try:
            if callback is not None:
                callback()
        finally:
            self._semaphore.release()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
