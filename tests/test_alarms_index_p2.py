"""Property-based test P2 for the potential-alarms index resolution order.

Hypothesis property P2: exact-then-stem-then-UNKNOWN resolution. Kept in its
own file (``_p2``) so it does not collide with the sibling P1/P3/P8 index tests.

The resolution contract under test (``PotentialAlarmsIndex.by_pod``):
  1. an exact ``pod`` key returns the stored record unchanged (mapped=True);
  2. a *different* name that shares the hash-stripped ``pod_stem`` of a stored
     pod but is not itself an exact key resolves via the stem fallback, returns
     ``mapped=True``, and the returned record's ``.pod`` is the QUERIED name
     (``model_copy(update={"pod": ...})`` carries it, not the stored name);
  3. a name matching neither an exact key nor any stored stem returns an
     UNKNOWN record (``mapped=False``) and never raises.

Stem siblings are built deterministically rather than hoping Hypothesis draws
two names that happen to share a stem: a plain base stem (no trailing hash
segments) is combined with two *different* replicaset+pod hash suffixes, each of
which the shipped ``pod_stem`` regex strips back to that same base. The property
quantifies over the generated base stems and hash suffixes, so the invariants
are asserted across a wide input space while the stem relationship stays exact.
"""
from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rca_agent.alarms.index import PotentialAlarmsIndex
from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms
from rca_agent.impact.loader import pod_stem

# A base stem with no trailing hash-ish segment, so pod_stem leaves it intact.
# Lowercase letters only, each dash-joined segment starting with a letter, so no
# segment can be mistaken for the numeric/hex hash suffixes the regex strips.
_SEGMENT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6)
_BASE_STEM = st.lists(_SEGMENT, min_size=1, max_size=3).map(lambda parts: "-".join(parts))

# A replicaset hash the regex recognises: 6-10 hex chars.
_RS_HASH = st.text(alphabet="0123456789abcdef", min_size=6, max_size=10)
# A pod-hash suffix the regex recognises: exactly 5 of [0-9a-z].
_POD_HASH = st.text(alphabet="0123456789abcdefghijklmnopqrstuvwxyz", min_size=5, max_size=5)


def _pod_name(base: str, rs: str, pod: str) -> str:
    """Compose '<base>-<rshash>-<podhash>' -- a deploy-style pod name that
    pod_stem strips back to ``base``."""
    return f"{base}-{rs}-{pod}"


def _record(pod: str) -> PotentialAlarms:
    """A mapped record whose single alarm's citation encodes the stored pod, so
    a returned record can be traced back to the stored entry it resolved from."""
    return PotentialAlarms(
        pod=pod,
        mapped=True,
        alarms=[CandidateAlarm(alarm_name="A", source_citation=f"src::{pod}")],
    )


# Feature: potential-alarms, Property 2: Exact-then-stem-then-UNKNOWN resolution
@settings(max_examples=100)
@given(
    base=_BASE_STEM,
    rs_stored=_RS_HASH,
    pod_stored=_POD_HASH,
    rs_sibling=_RS_HASH,
    pod_sibling=_POD_HASH,
    miss_base=_BASE_STEM,
)
def test_p2_exact_then_stem_then_unknown(
    base: str,
    rs_stored: str,
    pod_stored: str,
    rs_sibling: str,
    pod_sibling: str,
    miss_base: str,
) -> None:
    """``by_pod`` resolves exact key first, then the hash-stripped stem, then
    UNKNOWN -- and a stem hit yields ``mapped=True`` with ``.pod`` set to the
    queried name.

    Validates: Requirements 1.4
    """
    stored = _pod_name(base, rs_stored, pod_stored)
    sibling = _pod_name(base, rs_sibling, pod_stored) if rs_sibling == rs_stored else _pod_name(
        base, rs_sibling, pod_sibling
    )

    # The stem construction must actually hold under the real regex, and the
    # sibling must be a DIFFERENT name from the stored exact key (so the exact
    # branch cannot satisfy the stem-fallback assertions).
    assume(pod_stem(stored) == base)
    assume(pod_stem(sibling) == base)
    assume(sibling != stored)

    index = PotentialAlarmsIndex([_record(stored)])

    # (a) Exact key -> stored record, mapped=True, pod is the stored name, and
    # the stored citation proves it is the stored entry (not a copy).
    exact = index.by_pod(stored)
    assert exact.mapped is True
    assert exact.pod == stored
    assert exact.alarms[0].source_citation == f"src::{stored}"

    # (b) Stem sibling (shares base stem, not an exact key) -> resolves via the
    # stem fallback: mapped=True, the stored alarm payload, but .pod carries the
    # QUERIED name (model_copy), not the stored name.
    stem_hit = index.by_pod(sibling)
    assert stem_hit.mapped is True
    assert stem_hit.pod == sibling
    assert stem_hit.pod != stored
    assert stem_hit.alarms[0].source_citation == f"src::{stored}"

    # (c) A name matching neither an exact key nor any stored stem -> UNKNOWN.
    # Build a true miss on a base stem disjoint from the stored one; a trailing
    # ASCII sentinel keeps it off the stored stem even if miss_base == base.
    miss = f"{miss_base}-zzmiss"
    assume(miss != stored and miss != sibling)
    assume(pod_stem(miss) != base)
    missing = index.by_pod(miss)
    assert missing.mapped is False
    assert missing.pod == miss
    assert missing.alarms == []
