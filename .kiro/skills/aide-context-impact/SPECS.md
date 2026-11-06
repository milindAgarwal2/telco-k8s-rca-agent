# Context and impact skill specification

## Intent

Build the smallest useful context pack for a proposed change and trace its
consequences across repository boundaries.

## Input and output

Input is a change hypothesis and scope. Output is a revision-aware impact map
covering components, contracts, consumers, configuration, tests, and questions.

## Contract

Every relationship is evidence-backed or explicitly inferred. Graph retrieval
is optional discovery context, not authority, and cannot occur without existing
approved access.

## Failure handling

Stale, missing, or conflicting evidence is reported with its effect on the
analysis. The skill requires no environment variables itself.
