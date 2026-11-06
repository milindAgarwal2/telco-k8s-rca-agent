# Governance Status Policy

| Status | Meaning | Default action |
|---|---|---|
| Green | Exact detected version is approved/available | No governance action |
| Amber | Conditional status or approved component with version mismatch and known target | Plan tested alignment/upgrade |
| Yellow | Version or catalog status requires manual clarification | Resolve evidence or ask SCAS/3PPT owner |
| Red | Component/version is absent, denied, prohibited, unavailable, deprecated or EOL | Replace, upgrade or obtain exception |
| Grey | SCAS could not be queried reliably | Retry; do not infer availability |

## Precedence

Denied status overrides exact-version availability. Catalog failure is never
converted to Red. A source-only detection without a version is Yellow when the
component itself is known.

Exception: when a Stako comment explicitly says that a newer version exists,
all matching findings are consolidated under Amber, even when the comment does
not identify the target. The stable policy rule is
`STAKO-NEWER-VERSION-EXISTS`.

Approved internal component patterns have the highest precedence and use rule
`WHITELISTED-COMPONENT`. Defaults:

```text
docker.artifactory.rosetta*
docker.artifactory.rosetta.ericssondevops.com/*
```

A partial Maven library-name hit is Yellow with rule `PARTIAL-NAME-MATCH` until
the SCAS candidate is manually confirmed.

## Compliance score

The current report uses:

| Status | Weight |
|---|---:|
| Green | 1.00 |
| Amber | 0.65 |
| Yellow | 0.40 |
| Red | 0.00 |
| Grey | 0.00 |

The score is a prioritization aid, not an approval decision.

## Change control

Any change to mappings, default status or precedence requires:

1. a new `policy_version`;
2. updated unit tests;
3. approval from the SCAS/3PPT governance owner;
4. release notes describing changed outcomes.
