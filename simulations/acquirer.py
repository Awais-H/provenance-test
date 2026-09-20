"""The acquirer stand-in the settlement simulations submit against.

Its own module because more than one simulation needs it, and because the rule it
enforces is the point: the acquirer accepts one settlement instruction per merchant
per settlement date, and rejects a repeat of one. That is what makes a batch split
across two same-day submissions visible -- the first settles, the second is a
duplicate, and the merchant is paid for part of its night.

This repository does not vendor the acquirer client, so its error type is named here
rather than imported.
"""

from __future__ import annotations


class AcquirerError(Exception):
    """The acquirer client's rejection type.

    Named so a rejection reaches Sentry as `AcquirerError: <code>` rather than as a
    bare Exception shared with every other failure in the project.
    """


class LargeMerchantAcquirer:
    """Acknowledges a settlement instruction, and rejects a repeat of one.

    The instruction is keyed on (merchant, settlement date) -- the same key the
    acquirer's daily cap is expressed in, and the reason two submissions on one date
    cannot both be accepted.
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
