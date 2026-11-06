# Ansible content skill specification

## Intent

Author or review safe, explicit, idempotent Ansible content using repository
conventions and appropriate modules.

## Contract

Content defines its inventory boundary, variables, privilege, desired state,
side effects, failure behavior, handlers, approval, and rollback. Fully
qualified modules and existing validation are preferred.

## Failure handling

Expected exceptions use deliberate `failed_when`; unexpected failures are not
hidden. Live execution is never inferred from an authoring request.
