# Repository Security Audit Gate

This gate is a repository-local safety net for the execution and mutation boundaries already enforced at runtime.

It checks three invariants:

1. Production Python code does not invoke `subprocess` mutation/execution APIs outside the `ProcessSandbox` implementation, and does not enable `shell=True` or use `os.system`/`os.popen`.
2. Protected local credential filenames remain covered by `.gitignore`.
3. Python source files do not contain credential-shaped literals for common provider keys or bearer credentials.

The audit is intentionally conservative: a finding fails the gate rather than attempting to infer whether a direct execution path is safe.

Run locally with:

```text
python repository_security_audit.py
```

This gate does not grant execution, Git, network, or credential authority. It only inspects repository source/configuration and reports violations.
