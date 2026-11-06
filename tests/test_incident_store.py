"""DB-backed round-trip tests for the durable :class:`IncidentStore`.

These tests exercise the full ``model -> upsert -> load/get -> model`` path
against a real PostgreSQL ``incidents`` table. They are DB-backed and therefore
OPTIONAL: they run only when a test PostgreSQL is configured (see
``tests/conftest.py``'s ``pg_database`` fixture, which skips cleanly when no test
DSN is set or the ``psycopg`` driver is unavailable). Without a database this
module collects and skips rather than failing.

Coverage:

* ``test_incident_round_trip`` -- a richly populated ``IncidentReport`` (nested
  hypotheses with evidence chains, supporting evidence + citations, blast
  radius, upstream, affected pods, related incidents, a mapped service-area
  impact, and lifecycle fields) survives an upsert and reload via both
  ``get`` and ``load_recent`` with its serialized shape intact (Req 2.5, 7.3).
* ``test_upsert_updates_in_place`` -- re-upserting the same ``incident_id`` after
  mutating it updates the existing row in place (no duplicate) and the reloaded
  copy reflects the new fields (Req 2.5).
"""
from __future__ import annotations

from datetime import datetime, timezone

from rca_agent.impact.models import ServiceAreaImpact
from rca_agent.models.incident import (
    Citation,
    Evidence,
    Hypothesis,
    IncidentReport,
    Severity,
)
from rca_agent.store.incident_store import IncidentStore

# Fixed timestamps keep the tests deterministic (no wall-clock drift between
# the constructed model and the reloaded one).
_CREATED_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
_DETECTED_AT = datetime(2024, 1, 2, 3, 3, 0, tzinfo=timezone.utc)
_RESOLVED_AT = datetime(2024, 1, 2, 3, 30, 0, tzinfo=timezone.utc)
_CITATION_TS = datetime(2024, 1, 2, 3, 2, 0, tzinfo=timezone.utc)


def _clear_incidents(pg_database) -> None:
    """Empty the ``incidents`` table so each test starts from a clean slate."""
    with pg_database.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM incidents")
        conn.commit()


def _rich_report() -> IncidentReport:
    """Build a fully populated report touching every nested structure."""
    citation = Citation(
        kind="change",
        source="deployment/upf",
        detail="memory limit lowered 512Mi -> 128Mi",
        timestamp=_CITATION_TS,
        actor="kubectl",
        actor_source="human (kubectl)",
        is_automation=False,
    )
    supporting = Evidence(
        category="change",
        summary="UPF memory limit was lowered shortly before the incident",
        resource="deployment/upf",
        timestamp=_CITATION_TS,
        citations=[citation],
    )
    hypothesis = Hypothesis(
        cause="UPF OOMKilled after memory limit lowered",
        evidence_chain=[
            "SMF errors",
            "UPF unreachable",
            "UPF OOMKilled",
            "memory limit lowered",
        ],
        confidence=0.82,
        supporting_evidence=[supporting],
        citations=[citation],
    )
    service_area = ServiceAreaImpact(
        pod="upf-0",
        mapped=True,
        component="PC VPN Gateway Forwarder",
        service_area="VPN Gateway",
        section="18",
        relationship_type="Direct component match",
        confidence="High",
        component_sibling_count=3,
        service_area_pod_count=7,
    )
    return IncidentReport(
        incident_id="itest-roundtrip",
        created_at=_CREATED_AT,
        symptom="SMF reporting elevated 5xx to UPF",
        affected_resource="deployment/upf",
        affected_anchor="service/upf",
        anchor_kind="service",
        affected_pods=["upf-0", "upf-1"],
        namespace="core-5g",
        severity=Severity.critical,
        detected_at=_DETECTED_AT,
        status="inactive",
        resolved_at=_RESOLVED_AT,
        hypotheses=[hypothesis],
        blast_radius=["service/smf", "service/amf"],
        upstream_unhealthy=["deployment/upf"],
        evidence=[supporting],
        suggested_next_steps=["Raise the UPF memory limit back to 512Mi"],
        service_area=service_area,
        related_incidents=["itest-sibling-1", "itest-sibling-2"],
        reasoning_mode="extractive",
    )


def test_incident_round_trip(pg_database):
    """A rich report survives ``upsert`` -> ``get`` / ``load_recent`` intact.

    Every nested structure (hypotheses with evidence chains, supporting
    evidence and citations, service-area impact, blast radius, upstream,
    affected pods, related incidents) plus lifecycle fields must reload
    equivalent to the original. Equivalence is compared on the JSON-mode
    serialized form so enum and datetime encoding are compared consistently.

    Validates: Requirements 2.5, 7.3
    """
    pg_database.ensure_schema()
    _clear_incidents(pg_database)

    store = IncidentStore(pg_database)
    original = _rich_report()
    expected = original.model_dump(mode="json")

    store.upsert(original)

    fetched = store.get(original.incident_id)
    assert fetched is not None
    assert fetched.model_dump(mode="json") == expected

    recent = store.load_recent(1)
    assert len(recent) == 1
    assert recent[0].model_dump(mode="json") == expected


def test_upsert_updates_in_place(pg_database):
    """Re-upserting the same id updates the row in place (no duplicate).

    After an initial upsert (status active), mutating the same object and
    upserting again must leave ``count()`` unchanged for that id and have
    ``get()`` reflect the new fields (Req 2.5).

    Validates: Requirements 2.5, 7.3
    """
    pg_database.ensure_schema()
    _clear_incidents(pg_database)

    store = IncidentStore(pg_database)
    report = IncidentReport(
        incident_id="itest-inplace",
        created_at=_CREATED_AT,
        symptom="UPF pod crash looping",
        affected_resource="deployment/upf",
        affected_pods=["upf-0"],
        namespace="core-5g",
        severity=Severity.warning,
        status="active",
        related_incidents=["itest-sibling-1"],
    )
    store.upsert(report)
    assert store.count() == 1

    # Mutate the SAME object and re-persist: the row must be updated, not added.
    report.status = "inactive"
    report.resolved_at = _RESOLVED_AT
    report.affected_pods.append("upf-1")
    report.related_incidents.append("itest-sibling-2")
    store.upsert(report)

    # No duplicate row was created for this incident_id.
    assert store.count() == 1

    reloaded = store.get(report.incident_id)
    assert reloaded is not None
    assert reloaded.status == "inactive"
    assert reloaded.resolved_at == _RESOLVED_AT
    assert reloaded.affected_pods == ["upf-0", "upf-1"]
    assert reloaded.related_incidents == ["itest-sibling-1", "itest-sibling-2"]
    # Full serialized equivalence against the mutated in-memory object.
    assert reloaded.model_dump(mode="json") == report.model_dump(mode="json")
