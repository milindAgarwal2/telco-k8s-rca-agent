# Requirements Document

## Introduction

The Potential Alarms feature adds a new "Potential Alarms" section to the incident-details
panel of the RCA agent dashboard and to the per-incident PPTX export. For the pod(s)
currently having issues in an incident, the feature lists the **candidate alarms that could
have been raised for that pod**, grounded entirely in a curated pod-to-alarm mapping
workbook (`docs/analysis/cobra-pods-alarm-to-pod-mapping.xlsx`).

This feature is read-only, deterministic, and additive. It mirrors the already-shipped
service-area impact feature (`src/rca_agent/impact/`) in every structural respect: a curated
`.xlsx` workbook keyed by exact pod name, loaded once into an in-memory index; gated by a
single `RCA_*` path setting; inert when the path is unset or the file is missing; UNKNOWN
(never guessed) for pods absent from the workbook; every surfaced claim cites its workbook
source; and the result is an additive, defaulted field on `IncidentReport` that never changes
hypothesis ranking.

The defining distinction this feature must preserve throughout: these are **candidate**
("could have been raised") potential alarms derived from a curated mapping, **not** confirmed
active alarms. The agent is not observing alarm state; it is reporting which alarms the
curated mapping associates with an affected pod, and whether each association is a direct
pod-level mapping or a conditional candidate.

## Glossary

- **RCA_Agent**: The read-only Kubernetes fault detection and root-cause agent
  (`src/rca_agent/`) that produces incident reports. The containing system for all
  requirements below unless a narrower system is named.
- **Potential_Alarms_Loader**: The component that reads and parses the curated pod-to-alarm
  mapping workbook into structured in-memory records (mirrors `impact/loader.py`).
- **Potential_Alarms_Index**: The in-memory, queryable index that maps a pod name (exact,
  then hash-stripped stem) to its candidate alarm records (mirrors `impact/index.py`,
  `ServiceAreaIndex`).
- **Pod_Alarm_Workbook**: The curated Excel workbook
  `docs/analysis/cobra-pods-alarm-to-pod-mapping.xlsx` containing the "Pod Alarm Mapping"
  and "Alarm Reference" sheets.
- **Pod_Alarm_Map_Path**: The configuration value (`Settings.pod_alarm_map_path`, surfaced as
  the `RCA_POD_ALARM_MAP_PATH` environment variable) giving the filesystem path to the
  Pod_Alarm_Workbook.
- **Potential_Alarms**: The per-pod result model (mirrors `ServiceAreaImpact`) holding the pod
  name, a `mapped` flag, and an ordered list of Candidate_Alarm entries, plus a
  `summary_line()` method.
- **Candidate_Alarm**: One alarm association for a pod drawn from the "Pod Alarm Mapping"
  sheet: alarm name, alarm scope, severity, raise (condition) text, clear/reset condition
  text, applicability/qualification, mapping basis, and the PDF source citation.
- **Mapping_Basis**: The workbook's classification of how strongly an alarm associates with a
  pod. "Direct" means a pod-level condition directly mapped from the exact pod name;
  "Conditional candidate" means a name-derived workload/service mapping that depends on live
  cluster facts and alarm configuration and is not proven.
- **Alarm_Scope**: The workbook's scope classification for an alarm: "Individual pod",
  "Workload (container usage across workload)", or "Microservice/service".
- **Source_Citation**: The workbook's `Source in PDF` value for an alarm row (for example,
  `Pod related Alarms.pdf — "Pod Not Ready"`), surfaced verbatim as the evidence pointer for
  that Candidate_Alarm.
- **Affected_Pod**: A pod listed as having issues in an incident (`IncidentReport.affected_pods`,
  or the `affected_resource` anchor pod).
- **Incident_Report**: The agent's output schema (`src/rca_agent/models/incident.py`,
  `IncidentReport`).
- **Dashboard**: The server-rendered incident dashboard (`src/rca_agent/webhook/ui.py` and
  `webhook/templates/`).
- **PPTX_Report**: The per-incident PowerPoint export (`src/rca_agent/webhook/pptx_report.py`).
- **Inert**: A feature state in which no enrichment is attached and no error is raised,
  because the feature is not configured or its workbook is unavailable.
- **UNKNOWN**: The result state for a pod absent from the Pod_Alarm_Workbook: `mapped=False`
  with no Candidate_Alarm entries, explicitly distinguished from "no alarms could fire".

## Requirements

### Requirement 1: Load the curated pod-to-alarm workbook once, keyed by exact pod name

**User Story:** As an operator, I want the curated pod-to-alarm mapping loaded once at the
point of use and indexed by pod name, so that incident reports can look up candidate alarms
for an affected pod quickly and deterministically from reviewed data.

#### Acceptance Criteria

1. WHERE Pod_Alarm_Map_Path is set to a readable Pod_Alarm_Workbook, THE Potential_Alarms_Loader SHALL parse the "Pod Alarm Mapping" sheet into Candidate_Alarm records keyed by the exact `Pod name` column value, treating the key as case-sensitive and preserving the value with leading and trailing whitespace removed.
2. WHEN the Potential_Alarms_Loader parses the "Pod Alarm Mapping" sheet, THE Potential_Alarms_Loader SHALL read the header row that follows the title row and the disclaimer row, and SHALL extract the alarm name, alarm scope, severity, raise condition, clear/reset condition, applicability/qualification, mapping basis, and PDF source for each data row.
3. IF a data row is missing a non-blank `Pod name` value, THEN THE Potential_Alarms_Loader SHALL skip that row without adding a Candidate_Alarm record and without raising an exception.
4. WHEN a pod name is looked up, THE Potential_Alarms_Index SHALL attempt an exact pod-name match first and, only if no exact match exists, SHALL attempt a hash-stripped pod-stem match, and SHALL report the pod as UNKNOWN only when neither match exists.
5. WHERE Pod_Alarm_Map_Path is set and the workbook is readable, THE Potential_Alarms_Index SHALL load the mapping into memory once per reasoning lookup in the same manner as the service-area index, so that a re-supplied workbook takes effect on the next incident lookup.
6. WHERE Pod_Alarm_Map_Path is unset, THE Potential_Alarms_Index SHALL remain inert and SHALL return a Potential_Alarms result with `mapped` false for every queried pod name without raising an exception.
7. IF a looked-up pod name is empty or blank, THEN THE Potential_Alarms_Index SHALL return a Potential_Alarms result with `mapped` false and an UNKNOWN classification without raising an exception.
8. THE Potential_Alarms_Index SHALL expose a lookup that returns a Potential_Alarms result for any queried pod name without raising an exception.

### Requirement 2: Attach candidate alarms for each affected pod in an incident

**User Story:** As an operator triaging an incident, I want to see the alarms that could have
been raised for the affected pod(s), so that I know what monitoring signals to check without
the agent asserting those alarms are active.

#### Acceptance Criteria

1. WHEN an Incident_Report is produced AND the Potential_Alarms feature is configured, THE RCA_Agent SHALL resolve the Affected_Pod from the affected resource, and SHALL attach exactly one Potential_Alarms result for that pod.
2. IF no Affected_Pod can be resolved from the affected resource, THEN THE RCA_Agent SHALL resolve the Affected_Pod as the first pod in the incident's affected-pod list ordered as received.
3. IF the incident contains no affected pods, THEN THE RCA_Agent SHALL omit the Potential_Alarms result and SHALL leave the remainder of the Incident_Report unchanged.
4. WHERE an Affected_Pod is present in the Pod_Alarm_Workbook, THE Potential_Alarms result SHALL list every Candidate_Alarm mapped to that pod, each carrying its alarm name, Alarm_Scope, severity, raise condition, clear/reset condition, applicability/qualification, Mapping_Basis, and Source_Citation.
5. WHERE an Affected_Pod is present in the Pod_Alarm_Workbook but a listed Candidate_Alarm field value is absent in the workbook, THE Potential_Alarms result SHALL represent that field as the ASCII-safe literal UNKNOWN rather than omitting the field.
6. THE Potential_Alarms result SHALL order Candidate_Alarm entries so that all entries whose Mapping_Basis is Direct precede all entries whose Mapping_Basis is Conditional, preserving the workbook's relative order within each Mapping_Basis group.
7. THE Potential_Alarms result SHALL provide a `summary_line()` that returns one ASCII-safe sentence of at most 200 characters stating the pod name and the count of candidate alarms, or stating UNKNOWN when the pod is absent from the Pod_Alarm_Workbook.
8. WHERE the Potential_Alarms feature attaches a result for a pod present in the Pod_Alarm_Workbook, THE RCA_Agent SHALL record exactly one cited evidence item referencing the Pod_Alarm_Workbook as the source.

### Requirement 3: Report UNKNOWN for unmapped pods rather than guessing

**User Story:** As an operator, I want pods that are not in the curated mapping to be reported
as unknown, so that I never mistake an absent mapping for a statement that no alarms could
fire.

#### Acceptance Criteria

1. IF an Affected_Pod is absent from the Pod_Alarm_Workbook, THEN THE Potential_Alarms result SHALL set `mapped` to false and SHALL contain exactly zero Candidate_Alarm entries.
2. IF an Affected_Pod is absent from the Pod_Alarm_Workbook, THEN THE `summary_line()` SHALL state that potential alarms are UNKNOWN for that pod and SHALL indicate that the reason is that the pod is not mapped in the Pod_Alarm_Workbook.
3. IF an Affected_Pod is present in the Pod_Alarm_Workbook with one or more matching workbook rows, THEN THE Potential_Alarms result SHALL set `mapped` to true and SHALL contain one Candidate_Alarm entry for each matching workbook row.
4. THE Potential_Alarms_Index SHALL derive Candidate_Alarm entries only from the Pod_Alarm_Workbook and SHALL NOT infer, guess, or generate any Candidate_Alarm entry for a pod that has no matching workbook row.
5. WHEN an Affected_Pod is absent from the Pod_Alarm_Workbook, THE Potential_Alarms result SHALL represent the unmapped state (`mapped` false) as distinct from a mapped state that yields zero Candidate_Alarm entries, such that the two states are not reported identically.

### Requirement 4: Cite every surfaced alarm and present alarms as candidates, not confirmed

**User Story:** As an operator, I want each listed alarm to cite its source and to be clearly
framed as a candidate that could have been raised, so that I can trust the provenance and not
treat the list as confirmed active alarms.

#### Acceptance Criteria

1. WHEN a Candidate_Alarm is surfaced in any output, THE RCA_Agent SHALL include that alarm's Source_Citation (`Source in PDF`) value verbatim, character-for-character identical to the value recorded in the Pod_Alarm_Workbook with no truncation, reformatting, or substitution.
2. IF a Candidate_Alarm is surfaced without a non-empty Source_Citation value, THEN THE RCA_Agent SHALL omit that alarm from the output and record an indication that the alarm was suppressed for a missing citation, with all other surfaced alarms unaffected.
3. THE RCA_Agent SHALL label the Potential_Alarms section with text identifying it as candidate potential alarms that could have been raised, and SHALL NOT use the terms "confirmed" or "active" to describe entries in that section.
4. WHERE a Candidate_Alarm has Conditional candidate Mapping_Basis, THE RCA_Agent SHALL present that entry together with its applicability/qualification text recorded in the Pod_Alarm_Workbook, verbatim, indicating that the association depends on live cluster facts and alarm configuration.
5. THE RCA_Agent SHALL surface each Candidate_Alarm's Alarm_Scope and severity exactly as recorded in the Pod_Alarm_Workbook, with no normalization, reordering, or reclassification of either value.

### Requirement 5: Keep potential alarms as context, additive and backward-compatible

**User Story:** As a maintainer, I want the potential alarms to be pure context that never
alters cause ranking and never breaks existing reports, so that adding this feature is safe
for every existing consumer and the reasoning pipeline.

#### Acceptance Criteria

1. THE RCA_Agent SHALL expose the Potential_Alarms result as an additive field (`potential_alarms`) on Incident_Report that defaults to none when no potential alarms are produced.
2. WHILE hypotheses are being ranked, THE RCA_Agent SHALL leave each Hypothesis confidence value and the relative ordering of all hypotheses identical to the ordering produced when the Potential_Alarms result is absent.
3. THE Potential_Alarms result SHALL NOT create, remove, or reweight any Hypothesis, such that the count, identity, and confidence of hypotheses are unchanged whether the Potential_Alarms result is absent or present.
4. WHEN the Potential_Alarms feature is off, THE RCA_Agent SHALL serialize Incident_Report identically to its behavior before the `potential_alarms` field was introduced, with the `potential_alarms` field set to none.
5. IF producing the Potential_Alarms result fails for any reason, THEN THE RCA_Agent SHALL complete the Incident_Report with `potential_alarms` set to none, leave all hypothesis confidence and ordering unchanged, and log that potential-alarm context was unavailable.

### Requirement 6: Surface the Potential Alarms section in the dashboard and PPTX report

**User Story:** As an operator, I want the potential alarms shown in the incident-details
panel and the exported PPTX, so that I can review and share candidate alarms in the same
places I review the rest of an incident.

#### Acceptance Criteria

1. WHERE an Incident_Report has a Potential_Alarms result with one or more Candidate_Alarm entries, WHEN the operator opens the incident-details panel, THE Dashboard SHALL render a "Potential Alarms" section listing every Candidate_Alarm, where each entry displays its alarm name, Alarm_Scope, severity, Mapping_Basis, and Source_Citation, and no listed Candidate_Alarm is omitted.
2. WHERE an Incident_Report has a Potential_Alarms result with one or more Candidate_Alarm entries, IF any single Candidate_Alarm is missing a value for alarm name, Alarm_Scope, severity, Mapping_Basis, or Source_Citation, THEN THE Dashboard SHALL render that field as an explicit unknown indicator and SHALL render the remaining Candidate_Alarm entries without error.
3. WHERE an Incident_Report has a Potential_Alarms result marked UNKNOWN, WHEN the operator opens the incident-details panel, THE Dashboard SHALL render the "Potential Alarms" section containing a single statement that potential alarms are unknown because the pod is not mapped, and SHALL render no Candidate_Alarm entries.
4. WHERE an Incident_Report has a Potential_Alarms result, WHEN the PPTX_Report is generated, THE PPTX_Report SHALL include every Candidate_Alarm from that result, each paired with its Source_Citation value.
5. WHERE an Incident_Report has no Potential_Alarms result, WHEN the operator opens the incident-details panel, THE Dashboard SHALL omit the "Potential Alarms" section entirely and SHALL render the remaining incident-details panel content without error.

### Requirement 7: Remain read-only, deterministic, and free of LLM or cluster mutation

**User Story:** As a maintainer, I want the feature to be deterministic curated data only,
so that it cannot invent alarms, cannot depend on an LLM, and cannot change the cluster.

#### Acceptance Criteria

1. THE Potential_Alarms feature SHALL derive all output solely from the Pod_Alarm_Workbook and the queried pod name, using no other data source.
2. IF any output element cannot be traced to an entry in the Pod_Alarm_Workbook for the queried pod name, THEN THE Potential_Alarms feature SHALL exclude that element from the result.
3. THE Potential_Alarms feature SHALL operate without invoking any LLM.
4. THE Potential_Alarms feature SHALL perform no Kubernetes write, patch, or delete operation.
5. WHEN the same pod name is looked up against the same Pod_Alarm_Workbook, THE Potential_Alarms_Index SHALL return a result identical in content and ordering on every lookup.
6. IF the queried pod name has no matching entry in the Pod_Alarm_Workbook, THEN THE Potential_Alarms feature SHALL return a Potential_Alarms result with `mapped` false and no Candidate_Alarm entries, without modifying the Pod_Alarm_Workbook.

### Requirement 8: Degrade gracefully when unconfigured or when dependencies are absent

**User Story:** As an operator, I want the agent to run normally when the alarm mapping is
unconfigured, missing, or when optional parsing dependencies are absent, so that enabling or
disabling this feature never destabilizes the service.

#### Acceptance Criteria

1. WHERE Pod_Alarm_Map_Path is unset, THE Potential_Alarms feature SHALL be Inert, SHALL attach no Potential_Alarms result to any incident, and SHALL allow the reasoning pipeline to produce incidents identical to those produced when the feature is disabled.
2. IF Pod_Alarm_Map_Path is set but the referenced file is absent or cannot be opened for reading, THEN THE Potential_Alarms feature SHALL be Inert, SHALL attach no Potential_Alarms result, SHALL emit one log entry indicating the file is missing or unreadable, and SHALL complete the current reasoning cycle without raising an error to the caller.
3. IF the Pod_Alarm_Workbook is present but cannot be parsed, THEN THE Potential_Alarms feature SHALL be Inert, SHALL attach no Potential_Alarms result, SHALL emit one log entry indicating the parse failure, and THE reasoning pipeline SHALL complete the current cycle and produce its incident result without terminating or propagating the parse error.
4. IF the optional workbook-parsing dependency is unavailable when the Potential_Alarms feature is loaded, THEN THE Potential_Alarms feature SHALL be Inert, SHALL attach no Potential_Alarms result, and THE RCA_Agent SHALL complete startup and produce incidents identical to those produced when the feature is disabled.
