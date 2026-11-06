"""Property-based test P8 for the potential-alarms in-memory index.

Hypothesis property P8: lookups are deterministic. Querying the same pod name
twice against the SAME index returns results that are equal in content AND in
alarm ordering. Kept in its own file (``_p8``) so it does not collide with the
concurrently-authored P1/P2/P3 index tests.

The index is built directly from a KNOWN set of mapped ``PotentialAlarms`` --
the in-memory stand-in for the curated workbook -- so no file or openpyxl I/O
is required. The query is drawn to MIX the three resolution paths so
determinism is exercised across all of them:

* an EXACT stored pod name (hits ``_by_exact``);
* a name that shares a stored pod's hash-stripped stem but is not an exact key
  (hits ``_by_stem``, returning a copy carrying the queried name); and
* a name that resolves to nothing (the UNKNOWN / ``mapped=False`` path).
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rca_agent.alarms.index import PotentialAlarmsIndex
from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms
from rca_agent.impact.loader import pod_stem

# Pod names: non-blank after stripping so they form real exact keys / stems.
_POD = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="-",
    ),
    min_size=1,
    max_size=18,
).filter(lambda s: s.strip() != "")

_TEXT = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    max_size=24,
)


def _alarm(data: st.DataObject, pod_key: str, i: int) -> CandidateAlarm:
    """One CandidateAlarm. A mix of Direct and Conditional bases so the index's
    returned alarm ordering is non-trivial and the determinism check is
    meaningful."""
    return CandidateAlarm(
        alarm_name=data.draw(_TEXT, label=f"alarm[{pod_key}][{i}]"),
        scope=data.draw(_TEXT, label=f"scope[{pod_key}][{i}]"),
        severity=data.draw(_TEXT, label=f"sev[{pod_key}][{i}]"),
        mapping_basis=data.draw(
            st.sampled_from([
                "Exact pod name match",
                "Conditional candidate (workload-derived)",
            ]),
            label=f"basis[{pod_key}][{i}]",
        ),
        source_citation=f"src|{pod_key}#{i}",
    )


# Feature: potential-alarms, Property 8: Lookups are deterministic
@settings(max_examples=100)
@given(data=st.data())
def test_p8_lookups_are_deterministic(data: st.DataObject) -> None:
    """Query the same pod name twice against the SAME index; the two results
    are equal in content and in alarm ordering.

    The query is drawn to mix exact-hit, stem-hit, and miss paths so
    determinism is checked across every resolution branch of ``by_pod``.

    Validates: Requirements 7.5
    """
    # 1..4 distinct stored pods, each with 1..5 candidate alarms -> the
    # in-memory "workbook" the index is built from.
    pods = data.draw(
        st.lists(_POD, min_size=1, max_size=4, unique_by=lambda s: s.strip()),
        label="pods",
    )
    workbook: list[PotentialAlarms] = []
    for pod in pods:
        pod_key = pod.strip()
        n = data.draw(st.integers(min_value=1, max_value=5), label=f"n[{pod_key}]")
        alarms = [_alarm(data, pod_key, i) for i in range(n)]
        workbook.append(PotentialAlarms(pod=pod, mapped=True, alarms=alarms))

    index = PotentialAlarmsIndex(workbook)

    # Build a query that MIXES the three resolution paths:
    #  * exact     -> a stored pod name verbatim
    #  * stem-hit  -> a stored pod's stem suffixed with a hash-like token so it
    #                 is not an exact key but shares the stem
    #  * miss      -> a freely drawn name (may or may not resolve; included so
    #                 the UNKNOWN branch is also exercised across examples)
    stored = workbook[data.draw(
        st.integers(min_value=0, max_value=len(workbook) - 1),
        label="stored_idx",
    )]
    exact_query = stored.pod
    stem_query = f"{pod_stem(stored.pod)}-abcde12345"
    miss_query = data.draw(_POD, label="miss_query")
    query = data.draw(
        st.sampled_from([exact_query, stem_query, miss_query]),
        label="query",
    )

    # Two lookups of the SAME name against the SAME index.
    r1 = index.by_pod(query)
    r2 = index.by_pod(query)

    # Field-by-field equality (pydantic __eq__) -- covers content wholesale.
    assert r1 == r2
    # Explicit ordering guarantee: the alarm sequences are identical in order.
    assert [a for a in r1.alarms] == [a for a in r2.alarms]
    # Explicit identity fields: resolved pod name and mapped flag match.
    assert r1.pod == r2.pod
    assert r1.mapped == r2.mapped
