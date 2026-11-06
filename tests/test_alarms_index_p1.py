"""Property-based test for the potential-alarms index: totality of ``by_pod``.

Hypothesis property P1: ``PotentialAlarmsIndex.by_pod`` is a total function --
for any index (including an empty one) and any query string (empty, whitespace,
unicode, very long), it returns a ``PotentialAlarms`` and never raises.

Kept in its own file so it does not collide with the concurrently authored
index property tests P2 (``_p2``), P3 (``_p3``), and P8 (``_p8``).
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rca_agent.alarms.index import PotentialAlarmsIndex
from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms

# Query strings that stress totality: ordinary names, empty, whitespace-only,
# non-ASCII/unicode, and very long inputs.
_POD_QUERY = st.one_of(
    st.just(""),
    st.sampled_from([" ", "   ", "\t", "\n", " \t \n "]),
    st.text(max_size=80),
    st.text(
        alphabet=st.characters(min_codepoint=0x80, max_codepoint=0x2FFF),
        min_size=1,
        max_size=40,
    ),
    st.text(min_size=500, max_size=2000),  # very long
)

# Pod names used to populate the index (may overlap or differ from queries).
_INDEX_POD = st.text(max_size=60)

_CANDIDATE = st.builds(
    CandidateAlarm,
    alarm_name=st.text(max_size=40),
    scope=st.text(max_size=20),
    severity=st.text(max_size=20),
    mapping_basis=st.text(max_size=40),
)

_POTENTIAL_ALARMS = st.builds(
    PotentialAlarms,
    pod=_INDEX_POD,
    mapped=st.booleans(),
    alarms=st.lists(_CANDIDATE, max_size=5),
)


# Feature: potential-alarms, Property 1: by_pod is total and never raises
@settings(max_examples=100)
@given(
    items=st.lists(_POTENTIAL_ALARMS, max_size=8),
    query=_POD_QUERY,
)
def test_p1_by_pod_is_total_and_never_raises(
    items: list[PotentialAlarms],
    query: str,
) -> None:
    """For any index (empty list included) and any query string, ``by_pod``
    returns a ``PotentialAlarms`` instance and does not raise.

    Validates: Requirements 1.7, 1.8
    """
    index = PotentialAlarmsIndex(items)

    result = index.by_pod(query)

    assert isinstance(result, PotentialAlarms)
