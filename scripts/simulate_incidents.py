"""Drive the failure paths so the current release has incidents attached to it.

acme-payments is a library with no service to deploy, so nothing would ever throw in
production and Sentry would stay empty -- and an empty error tracker teaches
Provenance nothing. This script stands in for the traffic a real deployment would
have: it exercises each instrumented failure path once, against fake collaborators,
so every merge produces a small, stable set of issues whose `firstRelease` is that
merge's commit SHA.

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
from search import indexer  # noqa: E402
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


def simulate_index_dead_letter() -> None:
    """A bulk client that rejects everything, so the batch dead-letters in full."""

    class RejectingClient:
        def bulk_index(self, documents: list[dict]) -> list[dict]:
            return list(documents)

    documents = [{"id": f"merchant-{n}", "name": f"Merchant {n}"} for n in range(12)]
    with mock.patch.object(indexer.time, "sleep"):
        dropped = indexer.index_batch(RejectingClient(), documents)
    print(f"  index batch -> dropped={len(dropped)}")


def simulate_acquirer_timeout() -> None:
    """The acquirer never acknowledges -- the case SETTLEMENT_TIMEOUT_SECONDS exists for."""

    class TimingOutAcquirer:
        def submit(self, entries: list[dict], timeout: int) -> dict:
            raise TimeoutError(
                f"acquirer did not acknowledge {len(entries)} entries within {timeout}s"
            )

    entries = [{"merchant_id": "merchant_3902", "amount_cents": 250_000}] * 40
    try:
        settlement.submit_batch(TimingOutAcquirer(), entries)
    except TimeoutError as exc:
        print(f"  settlement batch -> {exc}")


def main() -> int:
    observability.init()
    release = os.environ.get("SENTRY_RELEASE") or "(none)"
    if not os.environ.get("SENTRY_DSN", "").strip():
        print("SENTRY_DSN is not set -- running the paths, reporting nothing.")
    print(f"simulating incidents for release {release}")

    simulate_dead_merchant_endpoint()
    simulate_index_dead_letter()
    simulate_acquirer_timeout()

    # The process is about to exit; without this the transport is torn down with
    # events still queued and the release looks clean.
    if observability.flush():
        print("flushed to Sentry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
