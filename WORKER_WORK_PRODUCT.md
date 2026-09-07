# Worker Work-Product Protocol

## Purpose

`WorkerWorkProduct` is the authoritative typed boundary between a specialist worker and the canonical orchestration layer. It replaces implicit, text-shaped worker output with a deterministic serializable envelope.

## Contract

A work-product contains:

- `task_id`, `worker_id`, and `role` identities;
- an exact, shell-free `action.command` tuple;
- exact execution-scope `action.targets`;
- optional explicitly declared external reads/writes;
- exact `mutation.changed_targets`;
- exact `FileChange(path, old_text, new_text)` records;
- structured `validation_evidence` supplied by the worker for later independent validation;
- `status` (`READY`, `NO_MUTATION`, or `FAILED`);
- structured failure information when status is `FAILED`.

## Authority boundary

The work-product is untrusted input. It does not authorize execution, filesystem mutation, or Git mutation. Existing `WorkerExecutionBoundary`, `IndependentValidator`, `ExecutionAuthorizationBoundary`, `ExecutionGate`, sandbox, and Git mutation control plane remain the only authorities for those actions.

The worker must not return raw shell syntax, shell wrappers, hidden filesystem targets, or an implicit mutation target set. `changed_targets` must match the `FileChange.path` set exactly. Identity must match the authoritative task assignment.

## Serialization

Schema version `1` is JSON-compatible and deterministic. `WorkerWorkProduct.from_dict()` validates the shape before any adapter can convert it into the legacy `WorkerExecutionSpec` compatibility view.

## Compatibility

`WorkerExecutionSpec` remains available as an internal compatibility representation for existing canonical tests and boundaries. New worker adapters should emit `WorkerWorkProduct`; the orchestrator normalizes it into the existing execution boundary without changing authority semantics.
