"""Property test P7 for the potential-alarms feature.

# Feature: potential-alarms, Property 7: summary_line() is ASCII-safe and bounded

Design (``.kiro/specs/potential-alarms/design.md``) states P7 as:

    *For any* ``PotentialAlarms`` result (mapped or unmapped, with any pod name
    and any alarm count), ``summary_line()`` returns a string that is
    ASCII-encodable and at most 200 characters long; when ``mapped`` is false
    the string states that potential alarms are UNKNOWN for the pod and that the
    reason is the pod is not mapped in the workbook.

This test encodes that property verbatim: it generates mapped and unmapped
``PotentialAlarms`` with *any* pod name (empty, ASCII, unicode, and long) and
any alarm count, then asserts ``summary_line()`` is ASCII-encodable and
``len <= 200``, plus the UNKNOWN wording for unmapped results.

NOTE (potential model defect surfaced by this property): ``summary_line()``
embeds ``self.pod`` verbatim with no truncation or ASCII sanitization, so a
unicode pod name makes ``s.encode("ascii")`` raise and a pod name longer than
~140 chars pushes the sentence past 200. The design asserts the property holds
for *any* pod name, so the generators below faithfully include unicode and long
names. If the model does not sanitize/truncate the embedded pod name, this test
will fail with a counterexample -- that failure is a real finding about the
model, not a test bug, and should be surfaced rather than masked by narrowing
the generators.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms

# "any pod name": empty, whitespace, realistic ASCII pod names, unicode, and
# long strings -- exactly the input space the design promises the property over.
_pod_names = st.one_of(
    st.text(),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=0, max_size=80),
    st.sampled_from(["", "   ", "upf-0", "smf-7c9-bbbb", "amf", "\u00e9toile-pod", "\u4e2d\u6587"]),
)

_alarms = st.lists(
    st.builds(CandidateAlarm, alarm_name=st.text(max_size=40)),
    max_size=20,
)


@settings(max_examples=100)
@given(pod=_pod_names, mapped=st.booleans(), alarms=_alarms)
def test_p7_summary_line_ascii_safe_and_bounded(pod: str, mapped: bool, alarms: list) -> None:
    """P7: summary_line() is ASCII-encodable, <= 200 chars, and states UNKNOWN
    plus the not-mapped reason for unmapped results, for any pod name and any
    alarm count."""
    pa = PotentialAlarms(pod=pod, mapped=mapped, alarms=alarms)

    line = pa.summary_line()

    # ASCII-safe: must encode without raising UnicodeEncodeError.
    line.encode("ascii")

    # Bounded: at most 200 characters.
    assert len(line) <= 200, f"summary_line() is {len(line)} chars (> 200): {line!r}"

    if not mapped:
        # Unmapped sentence must state UNKNOWN and the not-mapped-in-workbook reason.
        assert "UNKNOWN" in line, f"unmapped summary_line() missing UNKNOWN: {line!r}"
        assert "not mapped" in line.lower(), (
            f"unmapped summary_line() missing not-mapped reason: {line!r}"
        )
        assert "workbook" in line.lower(), (
            f"unmapped summary_line() missing workbook reference: {line!r}"
        )
