"""One night of large-merchant settlement, on the path submit_batch now chunks.

Standalone by design, and separate from scripts/simulate_incidents.py: that script
exercises the paths that were already instrumented before this change, and this one
stands up traffic for the path this PR opens. Batches over MAX_BATCH_ENTRIES used to
raise before they ever reached the acquirer, so nothing in the repository has ever
driven them.

Run it the same way as the other simulator, and against the same release:

    SENTRY_DSN=<dsn> SENTRY_RELEASE=$(git rev-parse HEAD) \\
      python simulations/oversized_settlement_batch.py

With SENTRY_DSN unset the traffic still runs and nothing is reported, which is the
quick way to check this file survives a change to settlement.py.

These are simulated incidents: real events from the real instrumentation in
payments/settlement.py, with real stack traces, but induced rather than observed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import observability  # noqa: E402
from payments import settlement  # noqa: E402

# A night's worth of merchants whose batches run past MAX_BATCH_ENTRIES, and the
# batch size one of them submits. 20,000 is two full submissions rather than a full
# one and a remainder, which is what the largest merchants actually look like.
LARGE_MERCHANT_COUNT = 40
LARGE_BATCH_ENTRIES = 20_000

SETTLEMENT_DATE = "2026-09-19"


class AcquirerError(Exception):
    """The acquirer client's rejection type, which this repository does not vendor.

    Named here so a rejection reaches Sentry as `AcquirerError: <code>` rather than
    as a bare Exception shared with every other failure in the project.
    """


class LargeMerchantAcquirer:
    """Acknowledges a settlement instruction, and rejects a repeat of one."""

    def __init__(self) -> None:
        self._instructions: set[tuple[str, str]] = set()

    def submit(self, entries: list[dict], timeout: int) -> dict:
        instruction = (entries[0]["merchant_id"], entries[0]["settlement_date"])
        if instruction in self._instructions:
            raise AcquirerError("DUPLICATE_INSTRUCTION")
        self._instructions.add(instruction)
        return {
            "accepted": len(entries),
            "batch_id": f"sim-{instruction[0]}-{len(self._instructions)}",
        }


def _entries_for(merchant_id: str) -> list[dict]:
    return [
        {
            "merchant_id": merchant_id,
            "settlement_date": SETTLEMENT_DATE,
            "amount_cents": 4_250,
        }
    ] * LARGE_BATCH_ENTRIES


def simulate_oversized_settlement_batches() -> tuple[int, int]:
    """Submit each large merchant's batch. Returns (settled, rejected)."""
    settled = rejected = 0
    for n in range(LARGE_MERCHANT_COUNT):
        merchant_id = f"merchant_{7000 + n}"
        # A fresh acquirer per merchant: the acquirer tracks instructions per
        # merchant, so one merchant's night says nothing about the next one's.
        try:
            settlement.submit_batch(LargeMerchantAcquirer(), _entries_for(merchant_id))
            settled += 1
        except AcquirerError as exc:
            # Already reported from settlement.submit_batch with its entry_count
            # tag; caught here only so the remaining merchants still run.
            rejected += 1
            print(f"  {merchant_id} -> {type(exc).__name__}: {exc}")
    return settled, rejected


def main() -> int:
    observability.init()
    release = os.environ.get("SENTRY_RELEASE") or "(none)"
    if not os.environ.get("SENTRY_DSN", "").strip():
        print("SENTRY_DSN is not set -- running the paths, reporting nothing.")
    print(f"simulating oversized settlement batches for release {release}")

    settled, rejected = simulate_oversized_settlement_batches()
    print(f"  oversized settlement batches -> settled={settled} rejected={rejected}")

    # The process is about to exit; without this the transport is torn down with
    # events still queued and the release looks clean.
    if observability.flush():
        print("flushed to Sentry")
    # Zero regardless. A rejection here is traffic being reported, not a broken
    # release job -- and failing the job would leave the release it just published
    # without the incidents that belong to it.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
