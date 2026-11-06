"""Property-based test P10 for the potential-alarms feature.

Property 10: Feature-off serialization is unchanged. A feature-off
``IncidentReport`` (``potential_alarms`` left at its ``None`` default) always
serializes with ``potential_alarms`` present and ``None`` -- never missing --
and survives a ``model_dump()`` -> re-construct round-trip unchanged. This
guards backward compatibility: adding the additive, defaulted field must not
alter the serialized shape or value of any report that does not use it.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rca_agent.models.incident import IncidentReport, Severity

# Varied values for a representative spread of IncidentReport's own fields. The
# feature field (``potential_alarms``) is deliberately never set, so every
# generated report is "feature off".
_text = st.text(max_size=40)
_opt_text = st.one_of(st.none(), st.text(max_size=40))
_str_list = st.lists(st.text(max_size=20), max_size=5)


# Feature: potential-alarms, Property 10: Feature-off serialization is unchanged
@settings(max_examples=100)
@given(
    symptom=_text,
    affected_resource=_opt_text,
    affected_anchor=_opt_text,
    anchor_kind=_opt_text,
    affected_pods=_str_list,
    namespace=_opt_text,
    severity=st.sampled_from(list(Severity)),
    status=st.sampled_from(["active", "inactive"]),
    blast_radius=_str_list,
    upstream_unhealthy=_str_list,
    suggested_next_steps=_str_list,
    related_incidents=_str_list,
    reasoning_mode=st.sampled_from(["extractive", "llm"]),
)
def test_p10_feature_off_serialization_unchanged(
    symptom: str,
    affected_resource: str | None,
    affected_anchor: str | None,
    anchor_kind: str | None,
    affected_pods: list[str],
    namespace: str | None,
    severity: Severity,
    status: str,
    blast_radius: list[str],
    upstream_unhealthy: list[str],
    suggested_next_steps: list[str],
    related_incidents: list[str],
    reasoning_mode: str,
) -> None:
    """A feature-off report serializes ``potential_alarms`` as an explicit
    ``None`` (present, not missing) and round-trips unchanged.

    Validates: Requirements 5.1, 5.4
    """
    report = IncidentReport(
        symptom=symptom,
        affected_resource=affected_resource,
        affected_anchor=affected_anchor,
        anchor_kind=anchor_kind,
        affected_pods=affected_pods,
        namespace=namespace,
        severity=severity,
        status=status,
        blast_radius=blast_radius,
        upstream_unhealthy=upstream_unhealthy,
        suggested_next_steps=suggested_next_steps,
        related_incidents=related_incidents,
        reasoning_mode=reasoning_mode,
    )

    # Feature is off: the field keeps its None default on the model.
    assert report.potential_alarms is None

    dumped = report.model_dump()

    # The key is PRESENT (backward-compat: serialized shape is stable) and its
    # value is explicitly None -- not dropped from the payload.
    assert "potential_alarms" in dumped
    assert dumped["potential_alarms"] is None

    # Round-trip: rebuilding from the dump yields an equal report whose feature
    # field is still None.
    restored = IncidentReport(**dumped)
    assert restored.potential_alarms is None
    assert restored == report

    # model_validate path round-trips identically too.
    revalidated = IncidentReport.model_validate(dumped)
    assert revalidated.potential_alarms is None
    assert revalidated == report
