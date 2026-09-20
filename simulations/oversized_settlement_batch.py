"""One night of large-merchant settlement, on the path that runs past the cap.

Standalone by design, and separate from scripts/simulate_incidents.py: that script
exercises the paths that were already instrumented, and this one stands traffic up
against the oversized-batch path, which nothing in the repository had ever driven.

Unlike the other simulator, this one is expected to report *nothing*. A merchant
over MAX_BATCH_ENTRIES settles what fits today and carries the remainder into the
next settlement date, and neither half is an error. If this file ever starts filing
issues, the deferral is broken -- most likely by something submitting the overflow
against the date that has already settled, which is the duplicate the cap exists to
prevent.

Run it the same way as the other simulator, and against the same release:

    SENTRY_DSN=<dsn> SENTRY_RELEASE=$(git rev-parse HEAD) \\
      python simulations/oversized_settlement_batch.py

With SENTRY_DSN unset the traffic still runs and nothing is reported, which is the
quick way to check this file survives a change to settlement.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import observability  # noqa: E402
from payments import settlement  # noqa: E402

# A night's worth of merchants whose batches run past MAX_BATCH_ENTRIES, and the
# batch size one of them submits. 20,000 is two full settlement dates' worth rather
# than one and a remainder, which is what the largest merchants actually look like.
LARGE_MERCHANT_COUNT = 40
LARGE_BATCH_ENTRIES = 20_000

# Tonight, and the date the overflow is carried into.
SETTLEMENT_DATE = "2026-09-19"
NEXT_SETTLEMENT_DATE = "2026-09-20"


class AcquirerError(Exception):
    """The acquirer client's rejection type, which this repository does not vendor.

    Named here so a rejection would reach Sentry as `AcquirerError: <code>` rather
    than as a bare Exception shared with every other failure in the project.
    """


class LargeMerchantAcquirer:
    """Acknowledges a settlement instruction, and rejects a repeat of one.

    The cap is per merchant per settlement date, so the instruction this rejects on
    is (merchant, date) -- the same key MAX_BATCH_ENTRIES is expressed in. This is
    the collaborator that makes a same-day split visible: chunk one settles, chunk
    two is a duplicate, and the merchant is paid for half its night.
    """

    def __init__(self) -> None:
        self.instructions: set[tuple[str, str]] = set()

    def submit(self, entries: list[dict], timeout: int) -> dict:
        instruction = (entries[0]["merchant_id"], entries[0]["settlement_date"])
        if instruction in self.instructions:
            raise AcquirerError("DUPLICATE_INSTRUCTION")
        self.instructions.add(instruction)
        return {
            "accepted": len(entries),
            "batch_id": f"sim-{instruction[0]}-{len(self.instructions)}",
        }


def _entries_for(merchant_id: str, settlement_date: str, count: int) -> list[dict]:
    return [
        {
            "merchant_id": merchant_id,
            "settlement_date": settlement_date,
            "amount_cents": 4_250,
        }
    ] * count


def simulate_deferred_settlement_batches() -> tuple[int, int, int]:
    """Settle each large merchant across two dates. Returns (settled, deferred, rejected)."""
    settled = deferred = rejected = 0
    for n in range(LARGE_MERCHANT_COUNT):
        merchant_id = f"merchant_{7000 + n}"
        # One acquirer per merchant, carried across both nights: it has to remember
        # tonight's instruction to reject a duplicate of it tomorrow.
        acquirer = LargeMerchantAcquirer()
        entries = _entries_for(merchant_id, SETTLEMENT_DATE, LARGE_BATCH_ENTRIES)
        try:
            _, overflow = settlement.submit_with_overflow(acquirer, entries)
            settled += 1
            if not overflow:
                continue
            # Tomorrow's run, with the overflow re-dated. Re-dating is the whole
            # point: the same entries against tonight's date are the duplicate.
            deferred += 1
            settlement.submit_batch(
                acquirer,
                _entries_for(merchant_id, NEXT_SETTLEMENT_DATE, len(overflow)),
            )
        except AcquirerError as exc:
            rejected += 1
            print(f"  {merchant_id} -> {type(exc).__name__}: {exc}")
    return settled, deferred, rejected


def check_oversized_batch_is_refused() -> bool:
    """A batch over the cap must fail before the acquirer ever sees it."""
    acquirer = LargeMerchantAcquirer()
    entries = _entries_for("merchant_7999", SETTLEMENT_DATE, LARGE_BATCH_ENTRIES)
    try:
        settlement.submit_batch(acquirer, entries)
    except ValueError as exc:
        # Nothing is reported here, and nothing should be: the guard raising is the
        # designed behaviour, and it raises before the instrumented submit.
        print(f"  oversized batch refused -> {exc}")
        return not acquirer.instructions
    print("  !! oversized batch was NOT refused -- the cap is not being enforced")
    return False


def main() -> int:
    observability.init()
    release = os.environ.get("SENTRY_RELEASE") or "(none)"
    if not os.environ.get("SENTRY_DSN", "").strip():
        print("SENTRY_DSN is not set -- running the paths, reporting nothing.")
    print(f"simulating oversized settlement batches for release {release}")

    refused = check_oversized_batch_is_refused()
    settled, deferred, rejected = simulate_deferred_settlement_batches()
    print(
        f"  large merchants -> settled={settled} deferred={deferred} "
        f"rejected={rejected}"
    )

    if observability.flush():
        print("flushed to Sentry")
    if rejected or not refused:
        # Printed, not raised: this job publishes a release, and failing it here
        # would leave that release without the incidents that belong to it. A
        # rejection has already reported itself from settlement.submit_batch.
        print("this simulation is meant to report nothing -- something regressed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
