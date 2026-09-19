"""Nightly settlement batch submission.

Settlement batches are submitted to the acquirer and acknowledged synchronously.
Large merchants submit batches big enough that the acquirer routinely takes over a
minute to acknowledge, so the timeout below is sized for the slowest observed
acknowledgement rather than the median.
"""

from __future__ import annotations

import logging

import observability

log = logging.getLogger(__name__)

# Raised from 30s after large-merchant batches began timing out mid-acknowledgement
# and settling twice on resubmit. See PR #3902.
SETTLEMENT_TIMEOUT_SECONDS = 90

MAX_BATCH_ENTRIES = 10000


def batch_total_cents(entries: list[dict]) -> int:
    """Total value of a batch, in cents."""
    return sum(e["amount_cents"] for e in entries)


def average_entry_cents(entries: list[dict]) -> int:
    """Mean entry value, in cents.

    Reported alongside the count because the count alone does not distinguish a
    thousand small card payments from a thousand large wire settlements, and the
    acquirer's acknowledgement latency tracks value far more closely than volume.

    An empty batch averages zero rather than raising. A merchant with nothing to
    settle is an ordinary night, not an error -- and this is reached from a log
    line, so raising here failed a submission that had nothing wrong with it.
    """
    if not entries:
        return 0
    return batch_total_cents(entries) // len(entries)


def submit_batch(acquirer, entries: list[dict]) -> dict:
    """Submit one settlement batch and return the acquirer acknowledgement."""
    if len(entries) > MAX_BATCH_ENTRIES:
        raise ValueError(f"batch of {len(entries)} exceeds {MAX_BATCH_ENTRIES}")
    log.info(
        "submitting settlement batch of %s entries, avg %s cents",
        len(entries),
        average_entry_cents(entries),
    )
    try:
        return acquirer.submit(entries, timeout=SETTLEMENT_TIMEOUT_SECONDS)
    except Exception as exc:
        # Captured and re-raised, so the caller's control flow is unchanged. The
        # explicit capture is here because a batch runner that catches this to move
        # on to the next merchant would otherwise hide a timeout -- and a timeout
        # mid-acknowledgement is exactly the double-settlement that set
        # SETTLEMENT_TIMEOUT_SECONDS to 90.
        observability.capture_exception(exc, entry_count=len(entries))
        raise
