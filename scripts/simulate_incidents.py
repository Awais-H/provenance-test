"""Drive the failure paths so the current release has incidents attached to it.

acme-payments is a library with no service to deploy, so nothing would ever throw in
production and Sentry would stay empty -- and an empty error tracker teaches
Provenance nothing. This script stands in for the traffic a real deployment would
have, deliberately narrowly: one failing path, against fake collaborators, so every
merge produces one issue rather than a list that buries the one being demonstrated.
Its `firstRelease` is that merge's commit SHA.

Scenarios that only added volume -- a dead-lettered index batch, an acquirer
timeout -- were removed for that reason. A path worth reporting gets its own file
under simulations/, where it is named and can be read on its own.

These are simulated incidents. They are real Sentry events, reported by the real
instrumentation in the real modules, with real stack traces -- but the failures are
induced, not observed. Do not read the issue counts as a health signal.

Run by .github/workflows/sentry-release.yml after the release is registered, so the
release exists before any event references it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import observability  # noqa: E402
from payments import settlement  # noqa: E402
from webhooks import delivery  # noqa: E402
from webhooks.types import Delivery  # noqa: E402

# Port 9 is the discard port: a connection there is refused immediately, so the
# webhook path fails the way a dead merchant endpoint does without waiting on a
# timeout and without touching the network.
DEAD_ENDPOINT = "http://127.0.0.1:9/webhooks/acme"


def simulate_dead_merchant_endpoint() -> None:
    """Every delivery attempt refused -- the retry budget burns and the event drops."""
    target = Delivery(
        merchant_id="merchant_4821",
        endpoint=DEAD_ENDPOINT,
        payload={"event": "payment.settled", "amount_cents": 1299},
        idempotency_key="sim-4821",
    )
    # The real backoff is 7s between four attempts. Waiting 21s in CI to prove a
    # connection is still refused buys nothing, so the sleep is stubbed -- the only
    # thing patched, and nothing Sentry sees depends on it.
    with mock.patch.object(delivery.time, "sleep"):
        delivered = delivery.deliver(target)
    print(f"  webhook delivery -> delivered={delivered}")


def simulate_empty_settlement_batch() -> None:
    """A merchant with nothing to settle. Ordinary, and must stay uneventful.

    Kept here because "nothing happened" is the case arithmetic over a batch tends
    to forget -- a totals or averages line added later divides by a count that is
    zero exactly on the nights there is nothing to report.
    """

    class QuietAcquirer:
        def submit(self, entries: list[dict], timeout: int) -> dict:
            return {"accepted": 0, "batch_id": "sim-empty"}

    ack = settlement.submit_batch(QuietAcquirer(), [])
    print(f"  empty settlement batch -> {ack}")


def main() -> int:
    observability.init()
    release = os.environ.get("SENTRY_RELEASE") or "(none)"
    if not os.environ.get("SENTRY_DSN", "").strip():
        print("SENTRY_DSN is not set -- running the paths, reporting nothing.")
    print(f"simulating incidents for release {release}")

    # Each scenario is isolated. A scenario that raises something the instrumented
    # code did not expect is exactly the interesting case -- it means a real bug,
    # and it must be reported rather than aborting the scenarios after it. Without
    # this, one regression silently costs the release every incident behind it.
    scenarios = (
        simulate_dead_merchant_endpoint,
        simulate_empty_settlement_batch,
    )
    failed = 0
    for scenario in scenarios:
        try:
            scenario()
        except Exception as exc:
            failed += 1
            print(f"  !! {scenario.__name__} raised {type(exc).__name__}: {exc}")
            observability.capture_exception(exc, scenario=scenario.__name__)

    # The process is about to exit; without this the transport is torn down with
    # events still queued and the release looks clean.
    if observability.flush():
        print("flushed to Sentry")
    # Zero regardless: an unhandled scenario is a finding to report, not a reason to
    # fail the release job that just published the release those findings belong to.
    if failed:
        print(f"{failed} scenario(s) raised unexpectedly -- reported to Sentry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
