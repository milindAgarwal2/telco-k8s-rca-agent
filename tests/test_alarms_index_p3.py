"""Property-based test P3 for the potential-alarms in-memory index.

Hypothesis property P3: absent pods yield UNKNOWN with zero alarms and nothing
is fabricated. Kept in its own file (``_p3``) so it does not collide with the
concurrently-authored P1/P2/P8 index tests.

The index is built directly from a KNOWN set of mapped ``PotentialAlarms`` --
the in-memory stand-in for the curated workbook -- so no file or openpyxl I/O
is required. Two things are asserted:

* an ABSENT pod (neither an exact stored key nor sharing a stored stem)
  resolves to ``mapped=False`` with an empty ``alarms`` list; and
* for ANY query, the returned alarms are a SUBSET of the alarms the workbook
  actually recorded -- the index never invents, infers, or fabricates an alarm.
  A present pod returns exactly its stored alarms; an absent pod returns none.
"""
from __future__ import annotations

from hypothesis import assume, given, settings
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
    """One CandidateAlarm whose source_citation carries a unique token, so a
    returned alarm can be identified unambiguously against the workbook."""
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


def _ids(alarms: list[CandidateAlarm]) -> set[str]:
    """Identify alarms by their unique source_citation token."""
    return {a.source_citation for a in alarms}


# Feature: potential-alarms, Property 3: Absent pods yield UNKNOWN with zero alarms and nothing is fabricated
@settings(max_examples=100)
@given(data=st.data())
def test_p3_absent_pods_unknown_and_no_fabrication(data: st.DataObject) -> None:
    """Build an index from a known workbook of mapped pods. An absent pod
    resolves to mapped=False with zero alarms; for any query the returned
    alarms are a subset of the workbook's rows for the resolved pod and are
    never fabricated.

    Validates: Requirements 3.1, 3.4, 7.1, 7.2, 7.6
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

    # The set of exact keys and stems that would resolve to a stored record.
    stored_exact = {rec.pod for rec in workbook}
    stored_stems = {pod_stem(rec.pod) for rec in workbook}
    # Every alarm id that the workbook actually recorded, anywhere.
    all_stored_ids = {
        a.source_citation for rec in workbook for a in rec.alarms
    }

    # --- (a) Absent pod: UNKNOWN with zero alarms ------------------------
    # Draw a candidate query and keep only names that cannot hit an exact key
    # or a shared stem, so the query is GUARANTEED absent from the index.
    candidate = data.draw(_POD, label="absent_candidate")
    assume(candidate not in stored_exact)
    assume(pod_stem(candidate) not in stored_stems)

    absent = index.by_pod(candidate)
    assert absent.mapped is False
    assert absent.alarms == []
    assert absent.pod == candidate
    # Nothing fabricated: the empty result draws from no workbook row.
    assert _ids(absent.alarms) == set()

    # --- (b) No fabrication for ANY query --------------------------------
    # For a present exact-key query, the returned alarms equal exactly the
    # stored alarms for that pod (a subset of the workbook, never more).
    present = workbook[data.draw(
        st.integers(min_value=0, max_value=len(workbook) - 1),
        label="present_idx",
    )]
    got = index.by_pod(present.pod)
    assert got.mapped is True
    assert _ids(got.alarms) == _ids(present.alarms)
    # Subset invariant holds against the whole workbook too: a returned alarm
    # is always one the workbook recorded -- never invented.
    assert _ids(got.alarms) <= all_stored_ids
    # And the absent query's (empty) result is trivially a subset as well.
    assert _ids(absent.alarms) <= all_stored_ids
