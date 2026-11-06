# Repository discovery skill specification

## Intent

Provide a repeatable, evidence-first orientation workflow for a heterogeneous
repository without changing it.

## Input and output

The input is a repository scope and discovery question. The output is a
source-linked inventory, an execution and validation guide, and unresolved
gaps.

## Contract

The skill must respect the requested scope, read applicable instructions,
distinguish static from target-dependent validation, and mark verified facts,
inference, and unknowns separately.

## Interactions and failures

It may consult source, tests, `knowledge-base/`, and `openwiki/`. Missing or
contradictory evidence becomes an explicit gap; it is never replaced by a
guess. It requires no environment variables.
