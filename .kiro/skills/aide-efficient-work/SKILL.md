---
name: aide-efficient-work
description: Use focused repository discovery and bounded context during coding, debugging, review, testing, and project analysis without reducing correctness or required evidence.
---
# Efficient engineering work

1. Interpret the user's actual objective. Do not require a token budget, special command,
   model choice, or context-engineering terminology.
2. Discover the relevant component with approved search, glob, or tree tools. Prefer
   LeanCTX `ctx_*` tools when available and follow their installed schemas.
3. Read the current implementation before editing. Keep enough context for callers,
   imports, contracts, tests, and failure behavior. Expand the range when uncertain.
4. Reuse a result only while its source is unchanged and its content remains available in
   the conversation. A cache hit or digest does not replace needed evidence.
5. Preserve test names, exit codes, relevant traces, and errors. Do not hide failures or
   combine commands to bypass approvals.
6. Implement and verify the requested outcome. Give a concise result with the details the
   user needs. Requested documents and teaching may legitimately be long.

Do not install tools, change models, clear conversations, modify global Kiro settings,
or weaken approvals merely to reduce tokens. Optional optimizer failure never blocks
normal work.
