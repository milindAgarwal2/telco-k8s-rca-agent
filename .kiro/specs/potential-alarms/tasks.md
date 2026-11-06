# Implementation Plan: Potential Alarms

## Overview

Convert the Potential Alarms design into a series of bounded, test-driven, incremental coding
steps. The feature is a symbol-for-symbol clone of the shipped `src/rca_agent/impact/` feature:
a four-file leaf sub-package (`src/rca_agent/alarms/`), a lazily-loaded workbook, an in-memory
index keyed by exact pod name with a hash-stripped stem fallback, a single `RCA_*` path gate, an
inert-when-unconfigured posture, an additive defaulted `IncidentReport` field, and a
context-not-cause reasoning step that never touches hypothesis ranking.

Each task builds on the previous ones and ends by wiring new code into an existing integration
point, so no code is left orphaned. Implementation language is **Python 3.10+** (the design
specifies concrete Python signatures). Conventions: ruff line length 100, pydantic `BaseModel`,
`from __future__ import annotations`, `src/` layout, pytest with `pythonpath=["src"]`, lazy
`openpyxl`, snake_case config fields surfaced as `RCA_`-prefixed env vars. The design includes a
Correctness Properties section (P1–P10), so property-based test sub-tasks (Hypothesis, ≥100
examples, tagged `Feature: potential-alarms, Property N`) are included and placed close to the
code they validate.

## Tasks

- [x] 1. Create the `alarms` leaf sub-package models
  - [x] 1.1 Implement `CandidateAlarm` and `PotentialAlarms` in `src/rca_agent/alarms/models.py`
    - Create `src/rca_agent/alarms/models.py` with `from __future__ import annotations`
    - Define `CandidateAlarm(BaseModel)` with fields `alarm_name: str`, and
      `scope`/`severity`/`raise_condition`/`clear_condition`/`applicability`/`mapping_basis`/
      `source_citation`/`workload_key` as `str = ""`, mirroring `impact/models.py` style
    - Add the `is_direct` property returning `"exact pod name" in mapping_basis.lower()`, with
      the docstring noting it only drives Direct-before-Conditional ordering and mutates nothing
    - Define `PotentialAlarms(BaseModel)` with `pod: str`, `mapped: bool = False`,
      `alarms: list[CandidateAlarm] = Field(default_factory=list)`
    - Implement `summary_line()` returning one ASCII-safe sentence ≤ 200 chars: mapped →
      "<pod> has N candidate potential alarm(s) ..."; unmapped → "Potential alarms UNKNOWN for
      <pod> (pod not mapped in the pod-alarm workbook)"
    - Include the "candidate that could have been raised — never observed/confirmed/active"
      class docstrings from the design
    - _Requirements: 2.6, 2.7, 3.2, 4.5_

  - [x] 1.2 Write property test P6 for verbatim field preservation
    - **Property 6: Field values are preserved verbatim**
    - Generate `source_citation`/`scope`/`severity` strings with punctuation, em-dashes, and
      quotes; assert the built `CandidateAlarm` returns them character-for-character unchanged
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 6`
    - _Requirements: 4.1, 4.5_

  - [x] 1.3 Write property test P7 for ASCII-safe, bounded `summary_line()`
    - **Property 7: `summary_line()` is ASCII-safe and bounded**
    - Generate mapped/unmapped `PotentialAlarms` with varying pod names and alarm counts; assert
      the result is ASCII-encodable and `len <= 200`, and that the unmapped sentence states
      UNKNOWN and the not-mapped reason
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 7`
    - _Requirements: 2.7, 3.2_

- [x] 2. Implement the workbook loader
  - [x] 2.1 Implement `src/rca_agent/alarms/loader.py`
    - Create the module with `from __future__ import annotations` and
      `from rca_agent.impact.loader import pod_stem` to reuse the shipped stem regex (single
      source of truth)
    - Define sheet constants `_ALARM_SHEET = "Pod Alarm Mapping"` and
      `_REFERENCE_SHEET = "Alarm Reference"` (reference sheet intentionally ignored)
    - Implement `_find_header_row(ws)` scanning from the top for the row whose first cell
      lower-strips to `"pod name"`, defaulting to row 1 when none is found
    - Implement `_header_map(ws, header_row)` (lowercased header text → 1-based column index at
      the located row) and `_col(hmap, *needles)` (first column whose lowered header contains
      all needles), reusing impact's substring approach
    - Implement `build_alarms(wb)` grouping every data row (header_row+1 .. max_row) by the exact
      stripped `Pod name` into one `PotentialAlarms` per pod; skip blank-`Pod name` rows; map all
      10 columns per the design; set `mapped=True` per grouped pod; order Direct-first then
      Conditional, stable within each group
    - Implement `load_workbook_alarms(path)` with the `openpyxl` import **inside** the function
      (read-only + `data_only`), building then closing the workbook
    - _Requirements: 1.1, 1.2, 1.3, 2.4, 2.6, 3.3_

  - [x] 2.2 Write property test P4 for grouping count equals matching rows
    - **Property 4: Grouping count equals matching workbook rows**
    - Build in-memory workbooks with N rows per pod (including blank-`Pod name` rows); assert the
      loaded `PotentialAlarms` has `mapped=True` and exactly N `CandidateAlarm` entries carrying
      every mapped field, and that blank-`Pod name` rows contribute no entry
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 4`
    - _Requirements: 1.3, 2.4, 3.3_

  - [x] 2.3 Write property test P5 for Direct-before-Conditional stable ordering
    - **Property 5: Direct-before-Conditional stable ordering**
    - Generate mixed Direct/Conditional rows for a single pod in random order; assert all
      `is_direct` entries precede non-direct entries and relative order is preserved within each
      group (stable partition)
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 5`
    - _Requirements: 2.6_

- [x] 3. Implement the in-memory index and factory
  - [x] 3.1 Implement `src/rca_agent/alarms/index.py`
    - Define `PotentialAlarmsIndex` building `_by_exact` keyed on `pod` and
      `_by_stem.setdefault(pod_stem(pod), item)` from the loaded items
    - Implement `by_pod(pod_name)`: empty/blank → `PotentialAlarms(pod=pod_name or "",
      mapped=False, alarms=[])`; exact hit → stored record; stem hit →
      `record.model_copy(update={"pod": pod_name})`; miss → unmapped record; never raises
    - Add `all()` and `__len__`
    - Implement `load_potential_alarms_index(path)` returning `None` when the path is falsy, the
      file is missing/unreadable, or parsing fails (wrap `load_workbook_alarms` in
      `try/except Exception`, log one info/warning), mirroring `load_service_area_index`
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8, 3.1, 3.4, 7.1, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4_

  - [x] 3.2 Add `src/rca_agent/alarms/__init__.py` re-exports
    - Re-export `CandidateAlarm`, `PotentialAlarms`, `PotentialAlarmsIndex`,
      `load_potential_alarms_index` via `__all__`, paralleling `impact/__init__.py`
    - _Requirements: 5.1_

  - [x] 3.3 Write property test P1 for total, non-raising `by_pod`
    - **Property 1: `by_pod` is total and never raises**
    - Generate arbitrary strings (empty, whitespace, unicode, very long) and arbitrary indexes;
      assert `by_pod` returns a `PotentialAlarms` and never raises
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 1`
    - _Requirements: 1.7, 1.8_

  - [x] 3.4 Write property test P2 for exact-then-stem-then-UNKNOWN resolution
    - **Property 2: Exact-then-stem-then-UNKNOWN resolution**
    - Generate mapped pods, rolled-hash stem variants, and true misses; assert exact→stem→UNKNOWN
      precedence and that a stem hit returns `mapped=True` with `pod` equal to the queried name
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 2`
    - _Requirements: 1.4_

  - [x] 3.5 Write property test P3 for UNKNOWN absent pods and no fabrication
    - **Property 3: Absent pods yield UNKNOWN with zero alarms and nothing is fabricated**
    - Generate pods absent from a known workbook; assert `mapped=False`, zero alarms, and that
      returned alarms are always a subset of the workbook's rows for the queried pod
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 3`
    - _Requirements: 3.1, 3.4, 7.1, 7.2, 7.6_

  - [x] 3.6 Write property test P8 for deterministic lookups
    - **Property 8: Lookups are deterministic**
    - Query the same pod name twice against the same index; assert equal content and alarm
      ordering
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 8`
    - _Requirements: 7.5_

- [x] 4. Build the committed test fixture
  - [x] 4.1 Implement `tests/fixtures/make_pod_alarm_fixture.py` and generate the workbook
    - Create the generator paralleling `tests/fixtures/make_service_area_fixture.py` using
      `openpyxl`
    - Produce a "Pod Alarm Mapping" sheet with a title row (row 1), a disclaimer row (row 2), and
      the row-3 header carrying all 10 columns in design order
    - Add several pods with multiple alarm rows mixing Direct and Conditional mapping bases, one
      row with a blank `Pod name`, and one row with an empty `Source in PDF`
    - Run the generator to write the committed `tests/fixtures/pod_alarm_mapping_sample.xlsx`
    - _Requirements: 1.2, 1.3, 2.4, 4.2_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Add the configuration gate
  - [x] 6.1 Add `pod_alarm_map_path` to `src/rca_agent/config.py`
    - Add `pod_alarm_map_path: str | None = None` next to `service_area_map_path`, with the
      inert-semantics comment and the `env RCA_POD_ALARM_MAP_PATH` note, matching the existing
      comment style
    - _Requirements: 1.5, 1.6, 8.1_

- [x] 7. Extend the incident model
  - [x] 7.1 Add `potential_alarms` field to `src/rca_agent/models/incident.py`
    - Add a top-level `from rca_agent.alarms.models import PotentialAlarms` import (parallel to
      the impact import)
    - Add `potential_alarms: PotentialAlarms | None = None` to `IncidentReport` with the
      context-not-cause doc comment from the design (additive, defaulted, never changes ranking)
    - _Requirements: 5.1, 5.4_

  - [x] 7.2 Write property test P10 for feature-off serialization
    - **Property 10: Feature-off serialization is unchanged**
    - Build feature-off `IncidentReport`s; assert `model_dump()` has `potential_alarms is None`
      and round-trips unchanged
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 10`
    - _Requirements: 5.1, 5.4_

- [x] 8. Wire the reasoning step
  - [x] 8.1 Add `potential_alarms` to `src/rca_agent/reasoning/state.py`
    - Add `potential_alarms: object = None` next to `service_area: object = None` (typed as
      `object` to avoid an import cycle)
    - _Requirements: 5.1_

  - [x] 8.2 Implement `build_potential_alarms` in `src/rca_agent/reasoning/steps.py`
    - Mirror `build_service_area`: no-op when `index is None`; resolve the affected resource then
      fall back to the first affected pod; on a mapped hit set `state.potential_alarms` and add
      exactly one `Evidence(category="alarms")` with one `Citation(kind="alarms",
      source="pod-alarm mapping workbook", ...)`; never create or reweight a `Hypothesis`
    - _Requirements: 2.1, 2.2, 2.3, 2.8, 3.1, 5.2, 5.3, 5.5, 7.3, 7.4_

  - [x] 8.3 Wire the step into `src/rca_agent/reasoning/extractive.py`
    - Add `from rca_agent.alarms.index import load_potential_alarms_index`
    - In `run`, after the `steps.build_service_area(...)` call, call
      `steps.build_potential_alarms(state, load_potential_alarms_index(self.cfg.pod_alarm_map_path))`
      (resolved fresh per incident, not cached)
    - In `_to_report`, add `potential_alarms=state.potential_alarms` alongside `service_area=...`
    - _Requirements: 1.5, 2.1, 5.1, 5.5_

  - [x] 8.4 Write property test P9 for ranking invariance
    - **Property 9: Attaching potential alarms never changes hypothesis ranking**
    - Run the pipeline feature-off vs feature-on over generated incident inputs; assert the
      hypotheses list is identical in count, identity, confidence, and relative ordering
    - Hypothesis, `@settings(max_examples=100)`, tag `Feature: potential-alarms, Property 9`
    - _Requirements: 5.2, 5.3_

  - [x] 8.5 Write loader and index example/edge tests (mirror `test_impact_loader.py`)
    - Loader example (R1 AC2, 1.5): parse the fixture; assert the header-row scan skips the
      title+disclaimer rows and all 10 columns map; a re-supplied fixture is visible on reload
    - Index edge cases (R1 AC7): `by_pod("")` and `by_pod("   ")` → `mapped=False`, no raise;
      exact, stem, and unmapped lookups over the fixture
    - UNKNOWN distinctness (R3 AC5): an unmapped `mapped=False` result is distinct from a mapped
      zero-alarm result
    - _Requirements: 1.1, 1.2, 1.3, 1.7, 3.5_

  - [x] 8.6 Write pipeline and graceful-degradation tests (mirror `test_impact_pipeline.py`)
    - Pipeline example (R2 AC1/2/3/8): mapped `affected_resource` attaches exactly one
      `PotentialAlarms` and exactly one `Evidence(category="alarms")`; empty resource falls back
      to the first affected pod; no affected pods → `potential_alarms` stays `None`
    - Context-not-cause example (R5 AC2/3): hypotheses list unchanged with the feature attached
    - Serialization/backward-compat (R5 AC1/4): feature off → `potential_alarms is None`
    - Graceful degradation (R8): factory returns `None` for unset path, missing file, and an
      unparsable workbook (one log each); simulated missing `openpyxl` keeps startup/incidents
      identical to disabled; a step-level failure leaves `potential_alarms=None` with unchanged
      ranking
    - _Requirements: 2.1, 2.2, 2.3, 2.8, 5.1, 5.4, 5.5, 8.1, 8.2, 8.3, 8.4_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Surface the section in the dashboard
  - [x] 10.1 Add the "Potential Alarms" block to `webhook/templates/_incident_detail.html`
    - Mirror the `service_area` block, wrapped in `{% if d.potential_alarms %}` so the section is
      omitted entirely when the field is `None`
    - Mapped + non-empty: render a header labelling entries as candidate potential alarms that
      could have been raised (never "confirmed"/"active"); per alarm render name, scope, severity,
      mapping basis, and source citation; render `applicability` verbatim for Conditional entries;
      render any missing field as an explicit unknown indicator; suppress entries whose
      `source_citation` is empty
    - Not mapped (UNKNOWN): render the section with a single not-mapped statement and no entries
    - _Requirements: 4.2, 4.3, 4.4, 6.1, 6.2, 6.3, 6.5_

  - [x] 10.2 Supply the render context in `src/rca_agent/webhook/ui.py`
    - Ensure the incident-detail render path passes `potential_alarms` to the template alongside
      the existing `service_area` context, mirroring the service-area wiring
    - _Requirements: 6.1, 6.5_

  - [x] 10.3 Write dashboard rendering tests (mirror `test_gui_service_area.py`)
    - Assert the fragment lists every candidate with name/scope/severity/mapping-basis/citation;
      the label states candidate alarms that could have been raised with neither "confirmed" nor
      "active" for entries; a missing field renders an explicit unknown indicator; an empty
      citation suppresses that entry; an UNKNOWN result renders the single not-mapped statement
      with zero entries; a `None` field omits the section and the rest of the panel renders
    - _Requirements: 4.2, 4.3, 4.4, 6.1, 6.2, 6.3, 6.5_

- [x] 11. Surface the section in the PPTX export
  - [x] 11.1 Add the candidate-alarm block to `src/rca_agent/webhook/pptx_report.py`
    - Mirror the slide-3 `service_area` block: read
      `pa = getattr(report, "potential_alarms", None)`; when `pa is not None and pa.mapped`, add a
      "Potential Alarms (candidates)" field listing each `CandidateAlarm` paired with its
      `source_citation`; label states candidates, never "confirmed"/"active"
    - _Requirements: 4.3, 6.4_

  - [x] 11.2 Write PPTX rendering test (mirror `test_pptx_report.py`)
    - Assert the generated deck includes each candidate paired with its source citation
    - _Requirements: 6.4_

- [x] 12. Finalize folder specs and relationship references
  - [x] 12.1 Add `src/rca_agent/alarms/SPECS.md` and reconcile parent references
    - Create `src/rca_agent/alarms/SPECS.md` mirroring `src/rca_agent/impact/SPECS.md` (purpose,
      components, data-flow diagram, inert/UNKNOWN/context-not-cause invariants)
    - Update `src/rca_agent/SPECS.md` and any relationship-map references to list the new
      `alarms/` sub-package alongside `impact/`
    - _Requirements: 5.1, 7.1_

- [x] 13. Final checkpoint - Run the verification gate
  - Run `make check` (ruff + pytest) and resolve any lint or test failures until the gate passes
  - Confirm the tagged property tests (P1–P10) and the mirrored example/GUI/PPTX tests execute
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test sub-tasks) and can be skipped for a faster MVP; core
  implementation tasks are never marked optional.
- Each task references the specific requirement sub-clauses it satisfies for traceability.
- Property-based tests use Hypothesis (≥100 examples) and are tagged
  `Feature: potential-alarms, Property N`; each of P1–P10 is a single property test placed close
  to the code it validates.
- Example, edge-case, GUI, PPTX, and graceful-degradation behaviors are verified by scenario
  tests (per the design's Testing Strategy), not by property tests.
- Checkpoints provide incremental validation; the final checkpoint runs the project gate
  `make check`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1", "6.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "7.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1", "7.2"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "8.1"] },
    { "id": 4, "tasks": ["8.2"] },
    { "id": 5, "tasks": ["8.3"] },
    { "id": 6, "tasks": ["8.4", "8.5", "8.6", "10.1", "11.1", "12.1"] },
    { "id": 7, "tasks": ["10.2", "10.3", "11.2"] }
  ]
}
```
