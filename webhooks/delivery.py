"""Webhook delivery to merchant endpoints.

Deliveries are attempted inline and retried with a fixed backoff when the
receiving endpoint is unavailable.
"""

from __future__ import annotations

import logging
import time

import requests

from .types import Delivery

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
DELIVERY_TIMEOUT_SECONDS = 10

# A response below this status counts as delivered. Named rather than left inline:
# a bare `300` inside an expression is invisible to anything that indexes
# identifiers, and the constant is what a reader searches for.
SUCCESS_STATUS_CEILING = 300

# The header merchants deduplicate on.
IDEMPOTENCY_HEADER = "Idempotency-Key"

# Retry spacing between delivery attempts. This has to clear an entire merchant
# failover window: at 5s we were still retrying inside the window and merchants
# accepted the same event twice (WEBHOOK-184, ENG-4821). 7s was measured against
# a real failover and held. Do not lower this without re-measuring the window.
RETRY_BACKOFF_SECONDS = 7


def deliver(delivery: Delivery) -> bool:
    """Attempt delivery, retrying on transport failure.

    The backoff is applied between attempts only -- never after the final attempt,
    which previously stalled the worker for a full RETRY_BACKOFF_SECONDS before
    giving up on a merchant that was never coming back.
    """
    for attempt in range(MAX_ATTEMPTS):
        if _attempt(delivery, attempt):
            return True
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_SECONDS)
    return False


def _attempt(delivery: Delivery, attempt: int) -> bool:
    try:
        response = requests.post(
            delivery.endpoint,
            json=delivery.payload,
            timeout=DELIVERY_TIMEOUT_SECONDS,
            headers={IDEMPOTENCY_HEADER: delivery.idempotency_key},
        )
    except requests.RequestException as exc:
        log.warning("delivery attempt %s failed for %s: %s", attempt, delivery.merchant_id, exc)
        return False
    return response.status_code < SUCCESS_STATUS_CEILING
