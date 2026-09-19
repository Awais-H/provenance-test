"""The single response contract every delivery surface consumes.

There is exactly one definition of what a context answer looks like. The HTTP API,
the CLI and the agent tool all render this model; none of them re-derives it. Three
slightly different definitions of "relevant" is precisely how surfaces drift apart,
so the model lives here and is imported, never reimplemented.

A surface supplies selection metadata and nothing else. Retrieval, ranking, conflict
detection and entity resolution all happen behind this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bumped whenever a field is removed or its meaning changes. Surfaces pin it so a
# contract change cannot silently half-deploy across three clients.
CONTRACT_VERSION = 1


@dataclass
class Selection:
    """Everything a surface is allowed to send. Deliberately small."""

    repo_path: str
    line_start: int
    line_end: int
    text: str


@dataclass
class Citation:
    """One piece of supporting evidence, with its provenance kept attached."""

    source: str
    url: str
    excerpt: str
    evidence: str


@dataclass
class Conflict:
    """Two citations that disagree, and which one won.

    Recorded rather than resolved silently: a superseded decision is still the
    reason the current code looks the way it does.
    """

    claim: str
    superseded_by: str
    rationale: str


@dataclass
class ContextResponse:
    """What every surface renders. No surface adds fields of its own."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    contract_version: int = CONTRACT_VERSION

    def is_null(self) -> bool:
        """True when nothing relevant was found.

        An explicit empty answer, never a fabricated one.
        """
        return not self.citations and not self.answer
