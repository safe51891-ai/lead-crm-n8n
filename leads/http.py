"""Resilient HTTP call with retries and exponential backoff for flaky third-party APIs (CRM, enrichment)."""
import time
from typing import Callable

RETRYABLE = {429, 500, 502, 503, 504}


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


def call_with_retries(send: Callable[[], tuple[int, dict]], retries: int = 3,
                      base_delay: float = 0.5, sleep: Callable[[float], None] = time.sleep) -> dict:
    """`send` returns (status_code, json_body). Retries only transient statuses; fails fast on 4xx."""
    last_status = None
    for attempt in range(retries + 1):
        status, body = send()
        if 200 <= status < 300:
            return body
        last_status = status
        if status not in RETRYABLE:
            raise PermanentError(f"non-retryable status {status}: {body}")
        if attempt < retries:
            sleep(base_delay * (2 ** attempt))
    raise TransientError(f"gave up after {retries + 1} attempts (last status {last_status})")
