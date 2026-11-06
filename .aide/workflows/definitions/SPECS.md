# Workflow Definition Specifications

## Intent

Each file in this folder is the normative, human-reviewable protocol for one
reusable workflow. Prompt launchers summarize and activate these definitions;
the definition controls when wording differs.

## Contract

Every definition states its trigger, exclusions, mandatory inputs, role and
skill assignments, phased outputs, evidence expectations, human gates, failure
behaviour, resumption rule, and completion criteria.

## Exception handling

A workflow stops when a required input, dependency, permission, evidence item,
or approval is absent. The stop report must preserve completed work and name
the smallest next action required to resume.

## Interactions

Definitions are indexed by `../catalog.json`, launched by `../prompts/`, and use
the portable artifacts in `../templates/`.


