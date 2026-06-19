from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import BoundedSemaphore


class ApiConcurrencyLimiter:
    def __init__(self, global_concurrency: int, user_ids: Sequence[str], per_user_concurrency: int) -> None:
        if global_concurrency < 1:
            raise ValueError("global_concurrency must be >= 1")
        if per_user_concurrency < 1:
            raise ValueError("per_user_concurrency must be >= 1")
        if not user_ids:
            raise ValueError("user_ids must not be empty")
        self._global = BoundedSemaphore(global_concurrency)
        self._per_user = {user_id: BoundedSemaphore(per_user_concurrency) for user_id in user_ids}

    @contextmanager
    def acquire(self, user_id: str) -> Iterator[None]:
        if user_id not in self._per_user:
            raise ValueError(f"unknown user_id: {user_id}")
        user_sem = self._per_user[user_id]
        user_sem.acquire()
        self._global.acquire()
        try:
            yield
        finally:
            self._global.release()
            user_sem.release()
