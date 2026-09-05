# AI-Agent Project Rules

## 1. Project truth
Use evidence in this order:
1. Actual files and project state
2. Executable tests/build/syntax results
3. Authoritative project specifications
4. Recorded architectural decisions
5. Model reasoning

Model reasoning alone cannot establish implementation or requirements.

## 2. Documentation
Documentation is control-plane input. Search for:
- specification
- requirements
- design
- architecture
- rules
- vision
- completion criteria
- testing requirements
- security constraints
- non-goals

Unresolved contradictions must be surfaced.

## 3. Automatic state classification
BUILD: specification/design exists and implementation is absent or minimal.

CONTINUE: implementation exists but required work remains.

MAINTAIN: project is substantially complete and stable.

REPAIR: confirmed test/build/syntax or equivalent failure.

CONFLICT: authoritative requirements contradict each other and cannot be safely reconciled.

UNKNOWN: insufficient evidence for a safe autonomous decision.

## 4. Autonomous start
Allowed: BUILD, CONTINUE, MAINTAIN, REPAIR, subject to validation/confidence policy.

Forbidden: UNKNOWN and unresolved CONFLICT.

## 5. No invented scope
Never invent requirements, perform unrelated refactors, modify unrelated files, or broaden scope without evidence.

## 6. Gap analysis
Completion percentage is not authoritative.

```text
What should exist
      vs
What actually exists
      =
Gap / Compliance
```

## 7. Minimal change
Prefer the smallest justified change with explicit target, exact old-state evidence, independent validation, and tests.

## 8. Uncertainty
When the answer is unclear:
- do not guess
- preserve last known-good state
- escalate or stop safely

## 9. Project memory
Verified architectural decisions and important failures should be preserved as structured state. Memory does not override current evidence.
