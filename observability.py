"""Sentry is optional here, exactly as it is in Provenance itself: with SENTRY_DSN
unset every function below is a no-op and this package behaves as though the SDK were
never installed. Nothing in acme-payments may depend on Sentry being configured.

What matters for Provenance is the *release*, not the DSN. `.github/workflows/
sentry-release.yml` registers each merge commit SHA as a Sentry release with that
PR's commits attached, and sets `SENTRY_RELEASE` to the same SHA when it runs the
code. Every issue therefore carries a `firstRelease` that is a merge commit SHA,
and GitHub reports that identical SHA as the PR's `merge_commit_sha`. That shared
string is what lets `provenance/integrations/sentry_issues.py` answer "which
incidents relate to PR #4" as an exact join instead of a full-text search for "#4".

Break that agreement -- version releases as semver, say -- and the join degrades
silently: Sentry keeps working, Provenance just stops finding incidents. The two
places that have to agree are the `release` input in the workflow and
`_release_for_pr` in the Provenance adapter.
"""

from __future__ import annotations

import os
from pathlib import Path

_initialised = False


def _load_dotenv() -> None:
    """Read a local .env, if there is one and python-dotenv is installed.

    Anchored to this file rather than the cwd, so running the simulator from a
    subdirectory still finds it. Never overrides a variable that is already set,
    which is what keeps CI correct: the workflow's SENTRY_RELEASE must win over a
    stale SHA someone left in a local .env.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def init() -> None:
    """Start the SDK if SENTRY_DSN is set. Safe to call more than once."""
    global _initialised
    if _initialised:
        return
    _load_dotenv()
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            # Unset outside CI, which leaves events with no release attached. That
            # is the honest answer for a working copy: an uncommitted tree is not a
            # release, and pretending otherwise would file its errors against
            # whatever SHA happened to be checked out.
            release=os.environ.get("SENTRY_RELEASE") or None,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
            traces_sample_rate=1.0,
            # Sentry's onboarding snippet suggests True. Deliberately not: the
            # webhook payloads and settlement entries on the scope here are merchant
            # data, and an error tracker is the wrong place for it. Nothing in the
            # PR->incident join needs it.
            send_default_pii=False,
            # Forwards stdlib `logging` to Sentry Logs, so the log.warning in
            # webhooks/delivery.py lands next to the issue it accompanies rather
            # than only on whichever worker emitted it. Logs pick up the same
            # release as events, so they are scoped to the PR too.
            enable_logs=True,
        )
        _initialised = True
    except Exception as exc:  # Sentry must never break the caller
        print(f"  ! sentry init failed, continuing without it: {exc}")


def _sdk():
    """The `sentry_sdk` module iff a client is actually active, else None.

    Asked per call rather than trusting `_initialised`, because a host application
    may have run `sentry_sdk.init()` itself before importing this package. Dropping
    its events because we were not the one who called init would be a worse bug than
    the negligible cost of checking.
    """
    try:
        import sentry_sdk
    except ImportError:
        return None
    return sentry_sdk if sentry_sdk.get_client().is_active() else None


def capture_exception(exc: BaseException, **tags) -> None:
    """Report an exception the caller is handling rather than propagating.

    Only worth calling where the exception is *swallowed*. Anything that escapes to
    the top of the process is already captured by the SDK's excepthook, and
    reporting it here as well would file the same failure as two issues.
    """
    sdk = _sdk()
    if sdk is None:
        return
    with sdk.new_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, str(value))
        sdk.capture_exception(exc)


def capture_message(message: str, level: str = "error", **tags) -> None:
    """Report a failure that never raised -- a budget exhausted, a batch dropped."""
    sdk = _sdk()
    if sdk is None:
        return
    with sdk.new_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, str(value))
        sdk.capture_message(message, level=level)


def flush(timeout: float = 10.0) -> bool:
    """Drain the queue before a short-lived process exits. True if there was one.

    A CLI or CI job exits fast enough to tear the transport down with events still
    queued, which shows up as a release that mysteriously has no issues.
    """
    sdk = _sdk()
    if sdk is None:
        return False
    sdk.flush(timeout=timeout)
    return True
