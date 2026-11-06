# Postman collection skill specification

## Intent

Analyze large Postman collections safely using a deterministic inventory before
targeted semantic review.

## Contract

Inventory output exposes structure and variable names but not secret values,
bodies, headers, or script source. Duplicate findings remain candidates until
behavioral equivalence is reviewed. Network execution is a separate action.

## Interactions

The skill uses `scripts/inventory_collection.py` locally through `uv` and may
read only the reviewed collection and related environment metadata.
