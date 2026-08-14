from app.runtime import LoginRateLimiter


def test_login_rate_limiter_window_backoff_reset_and_bound():
    now = [1000.0]
    limiter = LoginRateLimiter(
        max_attempts=2,
        window=100,
        lockout_base=10,
        max_tracked_ips=3,
        clock=lambda: now[0],
    )
    limiter.record_failure("a")
    limiter.record_failure("a")
    assert limiter.retry_after("a") == 10
    limiter.record_failure("a")
    assert limiter.retry_after("a") == 20

    limiter.reset("a")
    assert limiter.retry_after("a") == 0
    for ip in ("a", "b", "c", "d"):
        now[0] += 1
        limiter.record_failure(ip)
    assert len(limiter.snapshot()) == 3
    assert "a" not in limiter.snapshot()

    now[0] += 101
    limiter.prune()
    assert limiter.snapshot() == {}
