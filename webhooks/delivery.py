"""Webhook delivery to merchant endpoints.

Deliveries are attempted inline and retried with a fixed backoff when the
receiving endpoint is unavailable.
"""

from __future__ import annotations

import logging
import time

import requests

import observability

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

# Priority merchants run their own retry logic on top of ours, so a slow success is
# worse for them than a fast failure -- they are held to a tighter timeout than the
# standard tier.
DELIVERY_TIMEOUT_BY_TIER = {
    "standard": DELIVERY_TIMEOUT_SECONDS,
    "priority": 3,
}

# Retry spacing between delivery attempts. This has to clear an entire merchant
# failover window: at 5s we were still retrying inside the window and merchants
# accepted the same event twice (WEBHOOK-184, ENG-4821). 7s was measured against
# a real failover and held. Do not lower this without re-measuring the window.
RETRY_BACKOFF_SECONDS = 7


def _timeout_for(delivery: Delivery) -> int:
    """The delivery timeout for this merchant's tier.

    Absent or unrecognised tiers fall back to standard. The tier is written by the
    producer that enqueued the delivery, and deliveries enqueued before that
    producer learned to write it are still in the queue -- subscripting the payload
    directly took the whole worker down on the first one of those it picked up.
    """
    tier = delivery.payload.get("merchant_tier", "standard")
    return DELIVERY_TIMEOUT_BY_TIER.get(tier, DELIVERY_TIMEOUT_SECONDS)


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
            timeout=_timeout_for(delivery),
            headers={IDEMPOTENCY_HEADER: delivery.idempotency_key},
        )
    except requests.RequestException as exc:
        log.warning("delivery attempt %s failed for %s: %s", attempt, delivery.merchant_id, exc)
        # Reported as well as logged. This is the failure that motivated
        # RETRY_BACKOFF_SECONDS, and it is invisible above this frame -- `deliver`
        # returns a bool, so a merchant that is down for every attempt looks
        # identical to one that simply declined. The log line lives on whichever
        # worker happened to pick the delivery up; the Sentry issue is attached to
        # the release, and through it to the PR that shipped this backoff.
        observability.capture_exception(
            exc, merchant_id=delivery.merchant_id, attempt=attempt,
        )
        return False
    return response.status_code < SUCCESS_STATUS_CEILING
