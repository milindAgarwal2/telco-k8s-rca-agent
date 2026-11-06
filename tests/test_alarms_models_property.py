"""Property-based tests for the potential-alarms models.

Hypothesis property P6 for ``CandidateAlarm`` verbatim field preservation. Kept
in its own file so it does not collide with the example/P7 tests that target
``tests/test_alarms_models.py``.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rca_agent.alarms.models import CandidateAlarm

# Text that stresses verbatim preservation: ASCII punctuation, em-dashes, both
# straight and curly quotes, and other non-ASCII the workbook citations carry.
_FIELD_TEXT = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII incl. ' " ( ) , .
        st.sampled_from(["\u2014", "\u2013", "\u201c", "\u201d", "\u2018", "\u2019", "\u2026"]),
        # em-dash, en-dash, curly double quotes, curly single quotes, ellipsis
    ),
    max_size=120,
)


# Feature: potential-alarms, Property 6: Field values are preserved verbatim
@settings(max_examples=100)
@given(
    source_citation=_FIELD_TEXT,
    scope=_FIELD_TEXT,
    severity=_FIELD_TEXT,
    alarm_name=_FIELD_TEXT,
)
def test_p6_field_values_preserved_verbatim(
    source_citation: str,
    scope: str,
    severity: str,
    alarm_name: str,
) -> None:
    """A built ``CandidateAlarm`` returns its string fields character-for-
    character unchanged -- no normalization, trimming, or re-encoding.

    Validates: Requirements 4.1, 4.5
    """
    alarm = CandidateAlarm(
        alarm_name=alarm_name,
        source_citation=source_citation,
        scope=scope,
        severity=severity,
    )

    assert alarm.source_citation == source_citation
    assert alarm.scope == scope
    assert alarm.severity == severity
    assert alarm.alarm_name == alarm_name
