"""Shared webhook value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Delivery:
    """One webhook delivery attempt target."""

    merchant_id: str
    endpoint: str
    payload: dict
    idempotency_key: str
