---
inclusion: always
---
# Ponytail: choose the smallest sound implementation

Adapted for BOS AIDE from [Ponytail's Kiro steering](https://github.com/DietrichGebert/ponytail/blob/main/.kiro/steering/ponytail.md). Apply this during coding, refactoring, and bug fixes in Full and Extended workspaces.

Understand the requested behavior and trace the relevant code, callers, contracts,
and tests before choosing an approach. Then stop at the first option that meets
the requirement:

1. If the behavior is already present, show where it lives and avoid duplicating it.
2. Reuse a suitable repository helper or established pattern.
3. Use the standard library or a native platform capability.
4. Use an existing dependency when it fits.
5. Write only the new code needed for the accepted behavior.

For a bug, find the shared cause and fix it at the narrowest correct boundary.
Avoid speculative abstractions, dependencies, and scaffolding. Prefer a clear,
maintainable implementation over a shorter but fragile one.

The user's explicit scope, approved specifications, repository instructions, and
AIDE approval boundaries take precedence. Do not omit required tests, evidence,
error handling, security, accessibility, compatibility, or operational safeguards
to reduce lines of code. Use the repository's verification rules; Ponytail does
not impose a fixed number of tests. Follow AIDE's existing response-style and
Token Saver instructions for output and metrics.
