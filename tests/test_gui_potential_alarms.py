"""Dashboard tests: the 'Potential alarms' section of the incident detail.

Renders the _incident_detail.html partial directly through a Jinja environment
built over the shipped templates directory, with reports that carry (or omit) a
``potential_alarms`` result, and asserts the section content.

Mirrors ``test_gui_service_area.py`` in style, but builds the Jinja environment
locally instead of importing ``rca_agent.webhook.ui``. Importing the UI module
pulls in ``rca_agent.webhook.app`` (and therefore the psycopg-backed incident
store), which is unavailable in this offline env; rendering the template
directly keeps this test import-light and focused on template behavior.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from rca_agent.alarms.models import CandidateAlarm, PotentialAlarms
from rca_agent.models.incident import IncidentReport

# Point a Jinja environment straight at the shipped templates directory, the
# same folder ui.py uses, without importing the webhook app.
_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[1]
    / "src" / "rca_agent" / "webhook" / "templates"
)
_env = Jinja2Templates(directory=str(_TEMPLATES_DIR)).env


def _render(report: IncidentReport) -> str:
    tmpl = _env.get_template("_incident_detail.html")
    # Mirror the real inc_detail route: the template reads fields off the
    # JSON-dumped report dict (datetimes -> strings, potential_alarms -> nested
    # dict) with severity coerced to its string value.
    d = report.model_dump(mode="json")
    d["severity"] = getattr(report.severity, "value", report.severity)
    return tmpl.render(d=d, owners={}, pod_health=[], root="/")


def _alarms_section(html: str) -> str:
    """Return just the 'Potential alarms' section, from its heading to the
    next section heading ('Impact & dependencies'). The incident header always
    renders an 'active' status badge, so scope the candidate-framing assertions
    (no 'confirmed'/'active') to this section rather than the whole panel."""
    start = html.index("Potential alarms")
    end = html.index("Impact &amp; dependencies", start)
    return html[start:end]


def _direct_alarm(**overrides) -> CandidateAlarm:
    base = {
        "alarm_name": "Pod Not Ready",
        "scope": "Individual pod",
        "severity": "Major",
        "raise_condition": "pod not ready > 5m",
        "clear_condition": "pod ready",
        "mapping_basis": "Exact pod name match (Direct)",
        "source_citation": "Pod related Alarms.pdf -- Pod Not Ready (p.12)",
    }
    base.update(overrides)
    return CandidateAlarm(**base)


def _conditional_alarm(**overrides) -> CandidateAlarm:
    base = {
        "alarm_name": "Container CPU High",
        "scope": "Workload (container usage across workload)",
        "severity": "Minor",
        "applicability": "depends on live cluster CPU limits and alarm config",
        "mapping_basis": "Conditional candidate (name-derived workload)",
        "source_citation": "Workload Alarms.pdf -- CPU High (p.34)",
    }
    base.update(overrides)
    return CandidateAlarm(**base)


def _mapped_report(alarms: list[CandidateAlarm]) -> IncidentReport:
    pa = PotentialAlarms(
        pod="eric-pc-vpn-gateway-forwarder-85c5f46fc5-9zspm",
        mapped=True,
        alarms=alarms,
    )
    return IncidentReport(symptom="pod not ready",
                          affected_resource=pa.pod, potential_alarms=pa)


# --- Requirement 6.1 / 4.2: list every candidate with its fields + citation ---

def test_panel_lists_every_candidate_with_fields_and_citation():
    direct = _direct_alarm()
    conditional = _conditional_alarm()
    html = _render(_mapped_report([direct, conditional]))

    assert "Potential alarms" in html
    # Every candidate is listed by name.
    assert "Pod Not Ready" in html
    assert "Container CPU High" in html
    # Scope, severity, mapping basis and citation surface for each entry.
    assert "Individual pod" in html
    assert "Workload (container usage across workload)" in html
    assert "Major" in html
    assert "Minor" in html
    assert "scope:" in html
    assert "mapping basis:" in html
    assert "Pod related Alarms.pdf -- Pod Not Ready (p.12)" in html
    assert "Workload Alarms.pdf -- CPU High (p.34)" in html
    # Conditional entry surfaces its applicability text verbatim (R4.4).
    assert "depends on live cluster CPU limits and alarm config" in html


# --- Requirement 4.3 / 6.1: candidate framing, never "confirmed"/"active" ---

def test_panel_labels_candidates_and_avoids_confirmed_active():
    section = _alarms_section(_render(_mapped_report([_direct_alarm()])))
    # The label frames entries as candidates that could have been raised.
    assert "could have been raised" in section
    assert "candidate" in section.lower()
    # Within the potential-alarms section, neither "confirmed" nor "active" is
    # used to describe entries. (The incident header's 'active' status badge is
    # outside this section.)
    assert "confirmed" not in section.lower()
    assert "active" not in section.lower()


# --- Requirement 6.2: a missing field renders an explicit unknown indicator ---

def test_panel_missing_field_renders_unknown_indicator():
    # Severity and scope absent in the workbook (empty strings); citation kept
    # so the entry is not suppressed.
    alarm = _direct_alarm(severity="", scope="")
    html = _render(_mapped_report([alarm]))
    # The entry still renders (its citation is present) and shows explicit
    # unknown indicators rather than blank fields.
    assert "Pod Not Ready" in html
    assert "severity unknown" in html
    # Scope line renders an explicit unknown rather than an empty value.
    assert "scope:" in html
    assert "unknown" in html.lower()


# --- Requirement 4.2: an empty citation suppresses that entry ---

def test_panel_empty_citation_suppresses_entry():
    kept = _direct_alarm(alarm_name="Pod Not Ready")
    dropped = _direct_alarm(alarm_name="Silent Alarm", source_citation="")
    html = _render(_mapped_report([kept, dropped]))
    # The cited entry is listed; the uncited entry is suppressed.
    assert "Pod Not Ready" in html
    assert "Silent Alarm" not in html


# --- Requirement 3.x / 6.3: UNKNOWN result renders single not-mapped line ---

def test_panel_unknown_when_unmapped():
    pa = PotentialAlarms(pod="mystery-pod", mapped=False, alarms=[])
    report = IncidentReport(symptom="x", affected_resource="mystery-pod",
                            potential_alarms=pa)
    html = _render(report)
    assert "Potential alarms" in html
    assert "UNKNOWN" in html
    assert "not mapped" in html
    # Zero candidate entries: no alarm card icon is rendered.
    assert "🔔" not in html


# --- Requirement 6.5: a None field omits the section; rest of panel renders ---

def test_panel_absent_when_no_potential_alarms():
    report = IncidentReport(symptom="x", affected_resource="p")
    html = _render(report)
    assert "Potential alarms" not in html
    # The rest of the panel still renders.
    assert "Ranked hypotheses" in html
    assert "Impact &amp; dependencies" in html
