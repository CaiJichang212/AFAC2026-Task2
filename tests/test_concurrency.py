import threading

import pytest

from finix_restore.concurrency import ApiConcurrencyLimiter


WAIT_TIMEOUT = 2


def test_limiter_rejects_invalid_limits():
    with pytest.raises(ValueError, match="global_concurrency must be >= 1"):
        ApiConcurrencyLimiter(global_concurrency=0, user_ids=["u1"], per_user_concurrency=1)
    with pytest.raises(ValueError, match="per_user_concurrency must be >= 1"):
        ApiConcurrencyLimiter(global_concurrency=1, user_ids=["u1"], per_user_concurrency=0)
    with pytest.raises(ValueError, match="user_ids must not be empty"):
        ApiConcurrencyLimiter(global_concurrency=1, user_ids=[], per_user_concurrency=1)


def test_limiter_blocks_second_request_for_same_user_until_release():
    limiter = ApiConcurrencyLimiter(global_concurrency=2, user_ids=["u1"], per_user_concurrency=1)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_worker():
        with limiter.acquire("u1"):
            first_entered.set()
            assert release_first.wait(WAIT_TIMEOUT)

    def second_worker():
        assert first_entered.wait(WAIT_TIMEOUT)
        with limiter.acquire("u1"):
            second_entered.set()

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    second.start()

    assert first_entered.wait(WAIT_TIMEOUT)
    assert not second_entered.wait(0.1)
    release_first.set()
    first.join(timeout=WAIT_TIMEOUT)
    second.join(timeout=WAIT_TIMEOUT)

    assert second_entered.is_set()
    assert not first.is_alive()
    assert not second.is_alive()


def test_limiter_blocks_when_global_limit_is_exhausted_across_users():
    limiter = ApiConcurrencyLimiter(global_concurrency=1, user_ids=["u1", "u2"], per_user_concurrency=1)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_worker():
        with limiter.acquire("u1"):
            first_entered.set()
            assert release_first.wait(WAIT_TIMEOUT)

    def second_worker():
        assert first_entered.wait(WAIT_TIMEOUT)
        with limiter.acquire("u2"):
            second_entered.set()

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    second.start()

    assert first_entered.wait(WAIT_TIMEOUT)
    assert not second_entered.wait(0.1)
    release_first.set()
    first.join(timeout=WAIT_TIMEOUT)
    second.join(timeout=WAIT_TIMEOUT)

    assert second_entered.is_set()
    assert not first.is_alive()
    assert not second.is_alive()


def test_limiter_rejects_unknown_user_id():
    limiter = ApiConcurrencyLimiter(global_concurrency=1, user_ids=["u1"], per_user_concurrency=1)
    with pytest.raises(ValueError, match="unknown user_id: u2"):
        with limiter.acquire("u2"):
            pass
