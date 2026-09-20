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

# The acquirer's cap, per merchant per settlement *date* -- not per submission. An
# oversized batch therefore cannot be split across two same-day submissions: the
# second comes back as DUPLICATE_INSTRUCTION once the first has settled, and the
# merchant is paid for part of its night with no error anywhere that says so. That
# was tried in 2024 and is what this limit exists to prevent.
#
# So a batch over the cap fails here, loudly, and its overflow goes to the next
# settlement date via submit_with_overflow. A failed job is re-run in the morning;
# a half-settled merchant is a reconciliation break and a support case.
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
    """Submit one settlement batch and return the acquirer acknowledgement.

    Raises on a batch over MAX_BATCH_ENTRIES rather than splitting it; callers
    settling a merchant that size want submit_with_overflow.
    """
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


def submit_with_overflow(acquirer, entries: list[dict]) -> tuple[dict, list[dict]]:
    """Settle what fits today and hand back what does not.

    Returns the acknowledgement for this settlement date and the entries that did
    not fit, for the caller to carry into the next one. The overflow is returned
    rather than submitted because the cap is per settlement date: the remainder is
    only settleable once the date has rolled, and submitting it now is the duplicate
    MAX_BATCH_ENTRIES describes.
    """
    today, overflow = entries[:MAX_BATCH_ENTRIES], entries[MAX_BATCH_ENTRIES:]
    if overflow:
        # Warned rather than captured as an error: a deferral is the designed
        # outcome for a merchant this size, not a failure. It is loud enough to
        # notice a merchant deferring every night, which would mean their daily
        # volume has outgrown the cap and needs the acquirer, not a code change.
        log.warning(
            "deferring %s of %s entries to the next settlement date",
            len(overflow),
            len(entries),
        )
    return submit_batch(acquirer, today), overflow
