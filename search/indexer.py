"""Document indexer for the merchant search index.

Indexing is best-effort: a document that fails to index is retried with exponential
backoff and then dropped onto the dead-letter queue rather than blocking the batch.
This retry policy is unrelated to webhook delivery retries -- different system,
different failure mode, different constants.
"""

from __future__ import annotations

import logging
import random
import time

import observability

log = logging.getLogger(__name__)

INDEX_RETRY_ATTEMPTS = 3
INDEX_RETRY_BASE_SECONDS = 0.5
INDEX_BATCH_SIZE = 500


def backoff_delay(attempt: int) -> float:
    """Jittered exponential backoff: 0.5s, 1s, 2s (plus up to 25% jitter)."""
    return INDEX_RETRY_BASE_SECONDS * (2 ** attempt) * (1 + random.random() * 0.25)


def index_batch(client, documents: list[dict]) -> list[dict]:
    """Index `documents`, returning whatever could not be indexed after retries."""
    pending = list(documents)
    for attempt in range(INDEX_RETRY_ATTEMPTS):
        failed = client.bulk_index(pending)
        if not failed:
            return []
        log.warning("index attempt %s left %s documents failing", attempt, len(failed))
        pending = failed
        time.sleep(backoff_delay(attempt))
    if pending:
        # Best-effort indexing means the caller is entitled to ignore the return
        # value, and callers do. Without this, a batch silently dropping half its
        # documents every night produces no signal anywhere.
        observability.capture_message(
            f"index batch dropped {len(pending)} documents to the dead-letter queue",
            document_count=len(pending),
        )
    return pending
