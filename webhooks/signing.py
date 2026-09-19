"""Request signing for outbound webhooks.

Merchants verify an HMAC-SHA256 signature over the raw request body. The signing
secret is rotated per merchant; both the current and previous secret are accepted
during the rotation overlap so in-flight deliveries are not rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "X-Acme-Signature"
TIMESTAMP_HEADER = "X-Acme-Timestamp"

# How long a signature stays acceptable to the receiving merchant. Deliberately
# generous: merchants batch-process webhooks and we do not want clock skew on their
# side to reject a legitimate delivery.
SIGNATURE_TOLERANCE_SECONDS = 300

# Overlap during which the previous signing secret is still honoured.
SECRET_ROTATION_OVERLAP_SECONDS = 86400


def sign_body(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Return the signature header value for `body` under `secret`."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    signed_payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify(secret: str, body: bytes, header: str, now: int | None = None) -> bool:
    """Constant-time verification of a signature header produced by `sign_body`."""
    now = int(time.time()) if now is None else now
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(now - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    expected = sign_body(secret, body, timestamp).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))
