# Task planning skill specification

## Intent

Convert approved requirements and design into bounded, ordered, independently
verifiable implementation tasks.

## Contract

Every task traces to intent, names allowed scope and exclusions, declares
dependencies, and defines evidence, approvals, rollback, and escalation. Tasks
must not claim completion before verification.

## Failure handling

Missing approval, unresolved contract choices, or cross-repository uncertainty
blocks only the affected task and becomes an explicit planning dependency.
