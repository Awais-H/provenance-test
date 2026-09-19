"""Evidence policy: repository signals rank a result, they do not gate it.

A selection carries a path and a set of symbols. When a candidate names the same
path or symbol, that is strong evidence and it is boosted accordingly. When it does
not, the candidate stays eligible -- design discussions routinely predate the module
name they ended up describing, and discarding them would lose the decision that
explains the code.

The classification is reported alongside the result rather than hidden inside a
score, so a reader can tell a direct citation from a semantic match.
"""

from __future__ import annotations

# A candidate that names the selected path or one of its symbols.
EXACT = "exact"
# A candidate that discusses the same decision without naming the code.
SEMANTIC = "semantic"

# Multiplicative, deliberately not infinite: a path match is the strongest signal
# available but it cannot by itself outrank a directly on-topic discussion.
PATH_MATCH_BOOST = 1.8
SYMBOL_MATCH_BOOST = 1.4

# Below this a candidate is dropped entirely. Applied after boosting, so a weak
# semantic match with a path hit survives and a weak one without it does not.
MIN_RELEVANCE = 0.32


def classify(candidate_paths: list[str], candidate_symbols: list[str],
             selected_path: str, selected_symbols: list[str]) -> str:
    """Return EXACT when the candidate names the selection, SEMANTIC otherwise."""
    if selected_path and selected_path in candidate_paths:
        return EXACT
    if set(candidate_symbols) & set(selected_symbols):
        return EXACT
    return SEMANTIC


def score(base: float, candidate_paths: list[str], candidate_symbols: list[str],
          selected_path: str, selected_symbols: list[str]) -> float:
    """Boost `base` by whichever repository signals are present.

    Absence of a signal is never a penalty and never a filter -- it simply means
    the candidate is ranked on its semantic relevance alone.
    """
    boosted = base
    if selected_path and selected_path in candidate_paths:
        boosted *= PATH_MATCH_BOOST
    if set(candidate_symbols) & set(selected_symbols):
        boosted *= SYMBOL_MATCH_BOOST
    return boosted
