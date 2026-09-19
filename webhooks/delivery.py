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

# Retry spacing between delivery attempts.
RETRY_BACKOFF_SECONDS = 5


def deliver(delivery: Delivery) -> bool:
    """Attempt delivery, retrying on transport failure."""
    for attempt in range(MAX_ATTEMPTS):
        if _attempt(delivery, attempt):
            return True
        time.sleep(RETRY_BACKOFF_SECONDS)
    return False


def _attempt(delivery: Delivery, attempt: int) -> bool:
    try:
        response = requests.post(
            delivery.endpoint,
            json=delivery.payload,
            timeout=DELIVERY_TIMEOUT_SECONDS,
            headers={"Idempotency-Key": delivery.idempotency_key},
        )
    except requests.RequestException as exc:
        log.warning("delivery attempt %s failed for %s: %s", attempt, delivery.merchant_id, exc)
        return False
    return response.status_code < 300
