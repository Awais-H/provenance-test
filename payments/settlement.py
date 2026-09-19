"""Nightly settlement batch submission.

Settlement batches are submitted to the acquirer and acknowledged synchronously.
Large merchants submit batches big enough that the acquirer routinely takes over a
minute to acknowledge, so the timeout below is sized for the slowest observed
acknowledgement rather than the median.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Raised from 30s after large-merchant batches began timing out mid-acknowledgement
# and settling twice on resubmit. See PR #3902.
SETTLEMENT_TIMEOUT_SECONDS = 90

MAX_BATCH_ENTRIES = 10000


def submit_batch(acquirer, entries: list[dict]) -> dict:
    """Submit one settlement batch and return the acquirer acknowledgement."""
    if len(entries) > MAX_BATCH_ENTRIES:
        raise ValueError(f"batch of {len(entries)} exceeds {MAX_BATCH_ENTRIES}")
    log.info("submitting settlement batch of %s entries", len(entries))
    return acquirer.submit(entries, timeout=SETTLEMENT_TIMEOUT_SECONDS)
