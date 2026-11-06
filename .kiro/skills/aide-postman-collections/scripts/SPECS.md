# Postman inventory scripts specification

## Intent

Provide deterministic offline preprocessing so a large collection can be
understood without placing the full artifact or its sensitive values in model
context.

## Interface

`inventory_collection.py <collection.json>` reads one UTF-8 JSON file and emits
JSON to standard output. It exits `0` on success and `2` for an unreadable,
oversized, or invalid collection. `--max-bytes` bounds input size and
`--compact` changes only output whitespace.

## Data contract

Output includes the input path and hash, schema metadata, request paths and
methods, sanitized URL templates, referenced variable names, authentication
types, script counts, warnings, and deterministic duplicate candidates. It
must not output variable values, authentication values, headers, request bodies,
query values, or script source.

## Side effects and failures

The script performs no network access and no writes. Errors are written to
standard error without partial inventory output. It uses no environment
variables.
