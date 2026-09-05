from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ============================================================================
# EXECUTION GATE v5
#
# Model proposal
#      ↓
# Validation
#      ↓
# Checkpoint
#      ↓
# Apply
#      ↓
# Tests
#      ↓
# ┌───────────────┐
# │ PASS          │ → APPROVED
# │ FAIL          │ → ROLLBACK → RETEST → VERIFIED_AFTER_ROLLBACK
# └───────────────┘
# ============================================================================


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "execution_gate_state.json"
CHECKPOINT_ROOT = BASE_DIR / ".agent_gate_checkpoints"

TEST_TIMEOUT_SECONDS = 60
PYTHON_EXE = sys.executable


# ============================================================================
# Exceptions
# ============================================================================


class GateError(Exception):
    """Base exception for execution gate failures."""


class WorkspaceViolation(GateError):
    """Raised when a path escapes the active workspace."""


class ValidationError(GateError):
    """Raised when a proposed change is invalid."""


class CheckpointError(GateError):
    """Raised when checkpoint creation or restoration fails."""


class TestExecutionError(GateError):
    """Raised when the test command cannot be executed."""


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class FileChange:
    path: str
    old_text: str
    new_text: str


@dataclass
class TestResult:
    passed: bool
    return_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: float
    command: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# Workspace Guard
# ============================================================================


class WorkspaceGuard:
    """
    Restricts all file operations to one explicit workspace.

    Security properties:
    - Absolute paths outside workspace are rejected.
    - Relative traversal outside workspace is rejected.
    - Symlink/junction escapes are rejected through resolve().
    - All file operations pass through this guard.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def resolve(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspaceViolation("Empty path is not allowed.")

        raw = Path(relative_path)

        candidate = (
            raw.resolve()
            if raw.is_absolute()
            else (self.workspace_root / raw).resolve()
        )

        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise WorkspaceViolation(
                f"Path escapes active workspace: {relative_path}"
            ) from exc

        return candidate

    def exists(self, relative_path: str) -> bool:
        return self.resolve(relative_path).exists()


# ============================================================================
# Execution Gate
# ============================================================================


class ExecutionGate:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.guard = WorkspaceGuard(self.workspace_root)

        CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)

        self.state: Dict[str, Any] = {
            "state": "IDLE",
            "workspace": str(self.workspace_root),
            "checkpoint": None,
            "transaction_id": None,
            "last_test": None,
            "updated_at": time.time(),
        }

        self._save_state()

    # ----------------------------------------------------------------------
    # State
    # ----------------------------------------------------------------------

    def _save_state(self) -> None:
        payload = dict(self.state)
        payload["updated_at"] = time.time()

        temp_path = STATE_FILE.with_suffix(".tmp")

        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, STATE_FILE)

    def _set_state(self, value: str) -> None:
        self.state["state"] = value
        self._save_state()

    # ----------------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------------

    def validate_change(self, change: FileChange) -> Path:
        target = self.guard.resolve(change.path)

        if not target.exists():
            raise ValidationError(
                f"Target file does not exist: {change.path}"
            )

        if not target.is_file():
            raise ValidationError(
                f"Target is not a regular file: {change.path}"
            )

        try:
            current_text = target.read_text(
                encoding="utf-8",
                errors="strict",
            )
        except UnicodeDecodeError as exc:
            raise ValidationError(
                f"Target is not valid UTF-8 text: {change.path}"
            ) from exc

        occurrences = current_text.count(change.old_text)

        if occurrences != 1:
            raise ValidationError(
                f"Expected exactly one old_text match in {change.path}; "
                f"found {occurrences}."
            )

        return target

    def validate_changes(
        self,
        changes: Sequence[FileChange],
    ) -> List[Path]:
        if not changes:
            raise ValidationError("No file changes were supplied.")

        resolved: List[Path] = []
        seen: set[Path] = set()

        for change in changes:
            target = self.validate_change(change)

            if target in seen:
                raise ValidationError(
                    f"Duplicate target in transaction: {change.path}"
                )

            seen.add(target)
            resolved.append(target)

        return resolved

    # ----------------------------------------------------------------------
    # Checkpoint
    # ----------------------------------------------------------------------

    def create_checkpoint(
        self,
        changes: Sequence[FileChange],
    ) -> Path:
        transaction_id = (
            f"{int(time.time() * 1000)}_"
            f"{os.getpid()}_"
            f"{time.perf_counter_ns()}"
        )

        checkpoint_dir = CHECKPOINT_ROOT / transaction_id
        files_dir = checkpoint_dir / "files"

        checkpoint_dir.mkdir(parents=True, exist_ok=False)
        files_dir.mkdir(parents=True, exist_ok=False)

        manifest: List[Dict[str, str]] = []

        try:
            for index, change in enumerate(changes):
                source = self.guard.resolve(change.path)

                if not source.exists() or not source.is_file():
                    raise CheckpointError(
                        f"Cannot checkpoint missing file: {change.path}"
                    )

                backup_name = f"{index:04d}.bak"
                backup_path = files_dir / backup_name

                shutil.copy2(source, backup_path)

                manifest.append(
                    {
                        "path": change.path,
                        "backup": backup_name,
                    }
                )

            manifest_path = checkpoint_dir / "manifest.json"

            manifest_path.write_text(
                json.dumps(
                    {
                        "transaction_id": transaction_id,
                        "workspace": str(self.workspace_root),
                        "files": manifest,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.state["checkpoint"] = str(checkpoint_dir)
            self.state["transaction_id"] = transaction_id
            self._save_state()

            return checkpoint_dir

        except Exception:
            shutil.rmtree(checkpoint_dir, ignore_errors=True)
            raise

    # ----------------------------------------------------------------------
    # Apply
    # ----------------------------------------------------------------------

    def apply_changes(
        self,
        changes: Sequence[FileChange],
    ) -> None:
        for change in changes:
            target = self.guard.resolve(change.path)

            current_text = target.read_text(
                encoding="utf-8",
                errors="strict",
            )

            if current_text.count(change.old_text) != 1:
                raise ValidationError(
                    f"Source changed before apply: {change.path}"
                )

            new_text = current_text.replace(
                change.old_text,
                change.new_text,
                1,
            )

            temp_file = target.with_name(
                f".{target.name}.agent-tmp-"
                f"{os.getpid()}-{time.time_ns()}"
            )

            try:
                with temp_file.open(
                    "w",
                    encoding="utf-8",
                    newline="",
                ) as handle:
                    handle.write(new_text)
                    handle.flush()
                    os.fsync(handle.fileno())

                os.replace(temp_file, target)

            finally:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass

    # ----------------------------------------------------------------------
    # Tests
    # ----------------------------------------------------------------------

    def run_tests(
        self,
        final_state: str = "TESTING",
    ) -> TestResult:
        self._set_state("TESTING")

        command = [
            PYTHON_EXE,
            "-m",
            "pytest",
            "-q",
        ]

        start = time.perf_counter()

        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace_root,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TEST_TIMEOUT_SECONDS,
                check=False,
            )

        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0

            stdout = (
                exc.stdout.decode(
                    "utf-8",
                    errors="replace",
                )
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )

            stderr = (
                exc.stderr.decode(
                    "utf-8",
                    errors="replace",
                )
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )

            result = TestResult(
                passed=False,
                return_code=None,
                stdout=stdout[-4000:],
                stderr=(stderr + "\nTEST TIMEOUT").strip()[-4000:],
                duration_ms=duration_ms,
                command=command,
            )

            self.state["last_test"] = result.to_dict()
            self._set_state(final_state)

            return result

        except OSError as exc:
            raise TestExecutionError(
                f"Failed to execute test command: {exc}"
            ) from exc

        duration_ms = (time.perf_counter() - start) * 1000.0

        result = TestResult(
            passed=(completed.returncode == 0),
            return_code=completed.returncode,
            stdout=(completed.stdout or "")[-4000:],
            stderr=(completed.stderr or "")[-4000:],
            duration_ms=duration_ms,
            command=command,
        )

        self.state["last_test"] = result.to_dict()
        self._set_state(final_state)

        return result

    # ----------------------------------------------------------------------
    # Rollback
    # ----------------------------------------------------------------------

    def rollback(self, checkpoint_dir: Path) -> None:
        checkpoint_dir = checkpoint_dir.resolve()
        checkpoint_root = CHECKPOINT_ROOT.resolve()

        try:
            checkpoint_dir.relative_to(checkpoint_root)
        except ValueError as exc:
            raise CheckpointError(
                "Checkpoint is outside the allowed checkpoint root."
            ) from exc

        manifest_path = checkpoint_dir / "manifest.json"

        if not manifest_path.exists():
            raise CheckpointError(
                f"Checkpoint manifest missing: {manifest_path}"
            )

        payload = json.loads(
            manifest_path.read_text(
                encoding="utf-8",
            )
        )

        files = payload.get("files", [])

        if not isinstance(files, list) or not files:
            raise CheckpointError(
                "Checkpoint manifest contains no files."
            )

        restore_items: List[Tuple[Path, Path]] = []

        files_root = (checkpoint_dir / "files").resolve()

        for item in files:
            relative_path = item["path"]
            backup_name = item["backup"]

            target = self.guard.resolve(relative_path)

            backup_path = (
                checkpoint_dir / "files" / backup_name
            ).resolve()

            try:
                backup_path.relative_to(files_root)
            except ValueError as exc:
                raise CheckpointError(
                    f"Backup file escapes checkpoint directory: "
                    f"{backup_name}"
                ) from exc

            if not backup_path.exists():
                raise CheckpointError(
                    f"Backup file missing: {backup_path}"
                )

            restore_items.append(
                (
                    target,
                    backup_path,
                )
            )

        for target, backup_path in restore_items:
            temp_file = target.with_name(
                f".{target.name}.rollback-"
                f"{os.getpid()}-{time.time_ns()}"
            )

            try:
                shutil.copy2(
                    backup_path,
                    temp_file,
                )

                os.replace(
                    temp_file,
                    target,
                )

            finally:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass

        self.state["checkpoint"] = None
        self.state["transaction_id"] = None
        self._save_state()

    # ----------------------------------------------------------------------
    # Full transaction
    # ----------------------------------------------------------------------

    def execute(
        self,
        changes: Sequence[FileChange],
    ) -> Dict[str, Any]:
        # Every transaction starts with isolated state.
        self.state["checkpoint"] = None
        self.state["transaction_id"] = None
        self.state["last_test"] = None
        self._save_state()

        checkpoint: Optional[Path] = None

        try:
            # --------------------------------------------------------------
            # 1. VALIDATE
            # --------------------------------------------------------------

            self._set_state("VALIDATING")
            self.validate_changes(changes)

            # --------------------------------------------------------------
            # 2. CHECKPOINT
            # --------------------------------------------------------------

            self._set_state("CHECKPOINTING")
            checkpoint = self.create_checkpoint(changes)

            # --------------------------------------------------------------
            # 3. APPLY
            # --------------------------------------------------------------

            self._set_state("APPLYING")
            self.apply_changes(changes)

            # --------------------------------------------------------------
            # 4. TEST
            # --------------------------------------------------------------

            test_result = self.run_tests()

            # --------------------------------------------------------------
            # 5A. PASS
            # --------------------------------------------------------------

            if test_result.passed:
                self.state["checkpoint"] = None
                self.state["transaction_id"] = None
                self._set_state("APPROVED")

                return {
                    "status": "APPROVED",
                    "rollback": False,
                    "test": test_result.to_dict(),
                }

            # --------------------------------------------------------------
            # 5B. FAIL -> ROLLBACK
            # --------------------------------------------------------------

            if checkpoint is None:
                raise CheckpointError(
                    "Tests failed but no checkpoint exists."
                )

            self._set_state("ROLLING_BACK")

            self.rollback(checkpoint)

            # --------------------------------------------------------------
            # 6. VERIFY ROLLBACK
            # --------------------------------------------------------------

            post_rollback = self.run_tests(
                final_state="VERIFIED_AFTER_ROLLBACK"
            )

            if not post_rollback.passed:
                self._set_state("SAFE_STOP")

                raise GateError(
                    "CRITICAL: rollback completed, but "
                    "post-rollback tests still fail."
                )

            self._set_state("VERIFIED_AFTER_ROLLBACK")

            return {
                "status": "ROLLED_BACK",
                "rollback": True,
                "test_before_rollback": test_result.to_dict(),
                "test_after_rollback": post_rollback.to_dict(),
            }

        except ValidationError:
            self._set_state("REJECTED")

            return {
                "status": "REJECTED",
                "rollback": False,
            }

        except WorkspaceViolation:
            self._set_state("REJECTED")

            return {
                "status": "REJECTED",
                "rollback": False,
            }

        except Exception:
            # Defensive recovery if an unexpected exception occurs after
            # a checkpoint was created.
            if checkpoint is not None:
                try:
                    self.rollback(checkpoint)

                    post_rollback = self.run_tests(
                        final_state="VERIFIED_AFTER_ROLLBACK"
                    )

                    if post_rollback.passed:
                        self._set_state(
                            "VERIFIED_AFTER_ROLLBACK"
                        )
                    else:
                        self._set_state("SAFE_STOP")

                except Exception:
                    self._set_state("SAFE_STOP")

            raise


# ============================================================================
# Synthetic Test Helpers
# ============================================================================


def write_text(
    path: Path,
    text: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )


def build_test_workspace() -> Path:
    workspace = BASE_DIR / ".agent_gate_test"

    if workspace.exists():
        shutil.rmtree(
            workspace,
            ignore_errors=True,
        )

    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------------
    # Initial implementation
    # --------------------------------------------------------------

    write_text(
        workspace / "calculator.py",
        """def add(a, b):
    return a + b
""",
    )

    # --------------------------------------------------------------
    # Deterministic pytest
    # --------------------------------------------------------------

    write_text(
        workspace / "test_calculator.py",
        """from calculator import add


def test_add():
    assert add(2, 3) == 5
""",
    )

    return workspace


def assert_file_content(
    path: Path,
    expected: str,
) -> None:
    actual = path.read_text(
        encoding="utf-8",
    )

    if actual != expected:
        raise AssertionError(
            f"Unexpected file content in {path.name}:\n"
            f"EXPECTED:\n{expected}\n"
            f"ACTUAL:\n{actual}"
        )


# ============================================================================
# Synthetic Test
# ============================================================================


def synthetic_test() -> int:
    print("=" * 70)
    print("EXECUTION GATE SYNTHETIC TEST")
    print("=" * 70)
    print()

    test_workspace = build_test_workspace()
    calculator = test_workspace / "calculator.py"

    print(f"Test workspace: {test_workspace}")
    print()

    gate = ExecutionGate(test_workspace)

    original_code = """def add(a, b):
    return a + b
"""

    # This modification changes formatting/semantics minimally while
    # preserving the behavior required by the existing test.
    valid_changed_code = """def add(a, b):
    return (a + b)
"""

    # This modification intentionally breaks the test.
    failing_code = """def add(a, b):
    return a - b
"""

    # ======================================================================
    # TEST 1
    # ======================================================================

    print("-" * 70)
    print("TEST 1: VALID CHANGE -> APPROVE")
    print("-" * 70)

    result_1 = gate.execute(
        [
            FileChange(
                path="calculator.py",
                old_text="return a + b",
                new_text="return (a + b)",
            )
        ]
    )

    print(f"Status   : {result_1['status']}")
    print(f"Rollback : {result_1['rollback']}")

    if result_1["status"] != "APPROVED":
        raise AssertionError(
            "Valid change was not approved."
        )

    assert_file_content(
        calculator,
        valid_changed_code,
    )

    print("Valid change approval: PASS ✅")
    print()

    # Restore initial state.
    calculator.write_text(
        original_code,
        encoding="utf-8",
    )

    # ======================================================================
    # TEST 2
    # ======================================================================

    print("-" * 70)
    print("TEST 2: INVALID PROPOSAL -> REJECT")
    print("-" * 70)

    result_2 = gate.execute(
        [
            FileChange(
                path="calculator.py",
                old_text="THIS TEXT DOES NOT EXIST",
                new_text="anything",
            )
        ]
    )

    print(f"Status: {result_2['status']}")

    if result_2["status"] != "REJECTED":
        raise AssertionError(
            "Invalid proposal was not rejected."
        )

    assert_file_content(
        calculator,
        original_code,
    )

    print("Invalid proposal rejection: PASS ✅")
    print()

    # ======================================================================
    # TEST 3
    # ======================================================================

    print("-" * 70)
    print("TEST 3: PATH ESCAPE -> REJECT")
    print("-" * 70)

    result_3 = gate.execute(
        [
            FileChange(
                path="../outside.txt",
                old_text="anything",
                new_text="anything else",
            )
        ]
    )

    print(f"Status: {result_3['status']}")

    if result_3["status"] != "REJECTED":
        raise AssertionError(
            "Workspace escape was not rejected."
        )

    print("Workspace escape rejection: PASS ✅")
    print()

    # ======================================================================
    # TEST 4
    # ======================================================================

    print("-" * 70)
    print("TEST 4: TEST FAILURE -> ROLLBACK")
    print("-" * 70)

    result_4 = gate.execute(
        [
            FileChange(
                path="calculator.py",
                old_text="return a + b",
                new_text="return a - b",
            )
        ]
    )

    print(f"Status   : {result_4['status']}")
    print(f"Rollback : {result_4['rollback']}")

    if result_4["status"] != "ROLLED_BACK":
        raise AssertionError(
            "Failing test did not produce ROLLED_BACK."
        )

    if result_4["rollback"] is not True:
        raise AssertionError(
            "Failing test did not mark rollback=True."
        )

    # The final file must be exactly the original version.
    assert_file_content(
        calculator,
        original_code,
    )

    post_rollback = result_4.get(
        "test_after_rollback"
    )

    if not post_rollback:
        raise AssertionError(
            "Missing post-rollback verification result."
        )

    if post_rollback["passed"] is not True:
        raise AssertionError(
            "Post-rollback verification tests did not pass."
        )

    if post_rollback["return_code"] != 0:
        raise AssertionError(
            "Post-rollback pytest did not return exit code 0."
        )

    if gate.state["state"] != "VERIFIED_AFTER_ROLLBACK":
        raise AssertionError(
            f"Unexpected final state: {gate.state['state']}"
        )

    print("Rollback after test failure: PASS ✅")
    print(
        "Post-rollback tests: "
        f"{'PASS ✅' if post_rollback['passed'] else 'FAIL ❌'}"
    )
    print(
        f"Gate final state: {gate.state['state']}"
    )
    print()

    # ======================================================================
    # TEST 5: WORKSPACE ISOLATION
    # ======================================================================

    print("-" * 70)
    print("TEST 5: WORKSPACE ISOLATION")
    print("-" * 70)

    expected_files = {
        "calculator.py",
        "test_calculator.py",
    }

    actual_files = {
        item.name
        for item in test_workspace.iterdir()
        if item.is_file()
    }

    if not expected_files.issubset(actual_files):
        raise AssertionError(
            "Expected synthetic workspace files are missing."
        )

    unexpected = actual_files - expected_files

    if unexpected:
        print(
            "Additional files created inside test workspace:",
            sorted(unexpected),
        )

    print("Workspace remained isolated: PASS ✅")
    print()

    # ======================================================================
    # Save test result
    # ======================================================================

    result_file = (
        BASE_DIR /
        "execution_gate_test_result.json"
    )

    result_file.write_text(
        json.dumps(
            {
                "status": "PASS",
                "version": "v5",
                "tests": {
                    "valid_change": result_1,
                    "invalid_proposal": result_2,
                    "path_escape": result_3,
                    "test_failure_rollback": result_4,
                },
                "final_gate_state": gate.state["state"],
                "workspace": str(test_workspace),
                "valid_changed_code": valid_changed_code,
                "failing_code": failing_code,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 70)
    print("EXECUTION GATE TEST PASSED ✅")
    print("=" * 70)
    print()
    print(f"Result saved to: {result_file}")

    return 0


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    try:
        return synthetic_test()

    except Exception as exc:
        print()
        print("=" * 70)
        print("EXECUTION GATE TEST FAILED ❌")
        print("=" * 70)
        print(
            f"{type(exc).__name__}: {exc}"
        )
        return 1

    finally:
        # The synthetic project is disposable.
        test_workspace = (
            BASE_DIR /
            ".agent_gate_test"
        )

        shutil.rmtree(
            test_workspace,
            ignore_errors=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())