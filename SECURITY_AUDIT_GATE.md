# Repository Security Audit Gate

This gate is a repository-local safety net for the execution and mutation boundaries already enforced at runtime.

It checks three invariants:

1. Production Python code does not invoke `subprocess` execution/mutation APIs outside the established execution boundaries, and does not enable `shell=True` or use `os.system`/`os.popen`. Import aliases and `from ... import ...` aliases are analyzed as well.
2. Protected local credential filenames remain covered by `.gitignore`.
3. Production Python source does not contain credential-shaped literals for common provider keys or bearer credentials. Test modules may intentionally contain synthetic credential-shaped fixtures for redaction tests and are therefore excluded from this literal scan.

## Narrow legacy Git inspection exception

`project_scanner.py` currently contains a legacy read-only Git inspection path predating `ProcessSandbox`. It is not exempt as a module. The audit accepts only four exact Git commands:

- `git rev-parse --is-inside-work-tree`
- `git branch --show-current`
- `git rev-parse --show-toplevel`
- `git status --porcelain --untracked-files=all`

The exception requires each call to use literal or AST-proven constant arguments, `shell=False`, `check=False`, and a positive explicit timeout. Any other subprocess operation in `project_scanner.py`, including aliases, dynamic commands, missing bounds, or mutation commands, remains a finding.

This is a compatibility guard, not a new authority model. The intended end state is for the scanner's Git inspection to compose directly with the shared `ProcessSandbox` boundary.

The audit is intentionally conservative: a finding fails the gate rather than attempting to infer whether an unrelated subprocess path is safe.

Run locally with:

```text
python repository_security_audit.py
```

The CI gate can run the same command without installing project dependencies because the audit uses only the Python standard library.

This gate does not grant execution, Git, network, or credential authority. It only inspects repository source and configuration and reports violations.
