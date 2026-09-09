from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA_VERSION = 1
GENESIS_HASH = "GENESIS"

PROJECT_STATES = {"ACTIVE", "PAUSED", "COMPLETED", "SAFE_STOP"}
RUN_STATES = {
    "CREATED",
    "PLAN_ACCEPTED",
    "RUNNING",
    "PAUSED",
    "RECOVERING",
    "READY_TO_RESUME",
    "RECOVERY_REQUIRED",
    "COMPLETED",
    "FAILED",
    "SAFE_STOP",
}
PHASE_STATES = {"PENDING", "IN_PROGRESS", "INTERRUPTED", "COMPLETED", "FAILED", "RECOVERY_REQUIRED", "SAFE_STOP"}
TASK_STATES = {"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "INTERRUPTED", "RECOVERY_REQUIRED", "SAFE_STOP"}
ATTEMPT_STATES = {"STARTED", "FINISHED", "VALIDATED", "FAILED", "INTERRUPTED", "AMBIGUOUS", "RECOVERY_REQUIRED"}
CHECKPOINT_STATES = {"CREATED", "TRUSTED", "INVALID"}
ARTIFACT_STATES = {
    "ARTIFACT_VALIDATED",
    "ARTIFACT_UNVALIDATED",
    "ARTIFACT_INCOMPLETE",
    "ARTIFACT_INVALID",
    "ARTIFACT_AMBIGUOUS",
}
VALIDATION_STATES = {"PENDING", "PASSED", "FAILED", "REQUIRES_REVALIDATION"}
LEASE_STATES = {"ACTIVE", "RELEASED", "STALE", "RECLAIMED", "AMBIGUOUS"}
RECOVERY_STATES = {"NONE", "RECOVERING", "READY_TO_RESUME", "RECOVERY_REQUIRED", "SAFE_STOP"}
DELIVERY_STATES = {
    "DELIVERY_PENDING",
    "DELIVERY_STARTED",
    "DELIVERY_INTERRUPTED",
    "DELIVERY_RECOVERY_REQUIRED",
    "DELIVERY_COMMITTED",
    "DELIVERY_VERIFIED",
}
RECOVERY_OPERATION_STATES = {"PLANNED", "STARTED", "EFFECT_OBSERVED", "VERIFIED", "COMMITTED", "UNKNOWN", "FAILED"}

_ALLOWED_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "run": {
        "CREATED": {"PLAN_ACCEPTED", "SAFE_STOP"},
        "PLAN_ACCEPTED": {"RUNNING", "PAUSED", "RECOVERING", "SAFE_STOP"},
        "RUNNING": {"PAUSED", "RECOVERING", "COMPLETED", "FAILED", "SAFE_STOP"},
        "PAUSED": {"RUNNING", "RECOVERING", "SAFE_STOP"},
        "RECOVERING": {"READY_TO_RESUME", "RECOVERY_REQUIRED", "SAFE_STOP"},
        "READY_TO_RESUME": {"RUNNING", "PAUSED", "SAFE_STOP"},
        "RECOVERY_REQUIRED": {"RECOVERING", "SAFE_STOP"},
        "COMPLETED": set(),
        "FAILED": set(),
        "SAFE_STOP": set(),
    },
    "phase": {
        "PENDING": {"IN_PROGRESS", "SAFE_STOP"},
        "IN_PROGRESS": {"COMPLETED", "INTERRUPTED", "FAILED", "RECOVERY_REQUIRED", "SAFE_STOP"},
        "INTERRUPTED": {"RECOVERY_REQUIRED", "IN_PROGRESS", "SAFE_STOP"},
        "RECOVERY_REQUIRED": {"IN_PROGRESS", "SAFE_STOP"},
        "COMPLETED": set(),
        "FAILED": set(),
        "SAFE_STOP": set(),
    },
    "task": {
        "PENDING": {"IN_PROGRESS", "SAFE_STOP"},
        "IN_PROGRESS": {"COMPLETED", "FAILED", "INTERRUPTED", "RECOVERY_REQUIRED", "SAFE_STOP"},
        "INTERRUPTED": {"RECOVERY_REQUIRED", "IN_PROGRESS", "SAFE_STOP"},
        "RECOVERY_REQUIRED": {"IN_PROGRESS", "SAFE_STOP"},
        "COMPLETED": set(),
        "FAILED": set(),
        "SAFE_STOP": set(),
    },
    "attempt": {
        "STARTED": {"FINISHED", "VALIDATED", "FAILED", "INTERRUPTED", "AMBIGUOUS", "RECOVERY_REQUIRED"},
        "FINISHED": {"VALIDATED", "FAILED", "RECOVERY_REQUIRED"},
        "VALIDATED": set(),
        "FAILED": set(),
        "INTERRUPTED": {"RECOVERY_REQUIRED"},
        "AMBIGUOUS": {"RECOVERY_REQUIRED"},
        "RECOVERY_REQUIRED": set(),
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload_hash(payload: Mapping[str, Any]) -> str:
    return _hash_text(_canonical_json(dict(payload)))


def event_hash(
    *,
    run_id: str,
    sequence: int,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload_hash_value: str,
    previous_event_hash: str,
) -> str:
    material = "|".join(
        [
            run_id,
            str(sequence),
            event_type,
            entity_type,
            entity_id,
            payload_hash_value,
            previous_event_hash,
        ]
    )
    return _hash_text(material)


class DurableExecutionStateError(RuntimeError):
    """Base error raised by the durable execution state authority."""


class StateConflictError(DurableExecutionStateError):
    """Raised when a transition loses its sequence or state fence."""


class InvalidTransitionError(DurableExecutionStateError):
    """Raised for forbidden lifecycle transitions."""


class IntegrityError(DurableExecutionStateError):
    """Raised when durable state cannot be trusted."""


class LineageError(DurableExecutionStateError):
    """Raised when cross-project/run/task references are attempted."""


class RecoveryAmbiguityError(DurableExecutionStateError):
    """Raised when an ambiguous recovery operation cannot be safely replayed."""


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    project_id: str
    state: str
    sequence: int
    current_phase_id: Optional[str]
    current_task_id: Optional[str]
    last_checkpoint_seq: Optional[int]
    last_trusted_at: Optional[str]
    recovery_state: str
    recovery_started_at: Optional[str]
    recovery_sequence: int
    delivery_state: str


@dataclass(frozen=True)
class WorkspaceEvidence:
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    relative_path: str
    change_kind: str
    expected_before_identity: Optional[str]
    observed_before_identity: Optional[str]
    expected_after_identity: Optional[str]
    observed_after_identity: Optional[str]
    observed_state: str
    checkpoint_id: Optional[str]
    artifact_id: Optional[str]
    evidence_created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "phase_id": self.phase_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "relative_path": self.relative_path,
            "change_kind": self.change_kind,
            "expected_before_identity": self.expected_before_identity,
            "observed_before_identity": self.observed_before_identity,
            "expected_after_identity": self.expected_after_identity,
            "observed_after_identity": self.observed_after_identity,
            "observed_state": self.observed_state,
            "checkpoint_id": self.checkpoint_id,
            "artifact_id": self.artifact_id,
            "evidence_created_at": self.evidence_created_at,
        }


class DurableExecutionState:
    """Single Core authority for persistent Project/Run execution state.

    This layer stores lifecycle/evidence metadata only. It does not own worker
    routing, model selection, filesystem mutation, validation algorithms,
    delivery execution, Git mutation, or secrets.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.database_path),
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._initialize_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _configure(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=10000")

    def _initialize_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS schema_meta (
            schema_version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            workspace_root TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('ACTIVE','PAUSED','COMPLETED','SAFE_STOP'))
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            current_phase_id TEXT,
            current_task_id TEXT,
            last_checkpoint_seq INTEGER,
            last_trusted_at TEXT,
            recovery_state TEXT NOT NULL,
            recovery_started_at TEXT,
            recovery_sequence INTEGER NOT NULL,
            delivery_state TEXT NOT NULL,
            UNIQUE(project_id, run_id),
            FOREIGN KEY(project_id) REFERENCES projects(project_id)
        );

        CREATE TABLE IF NOT EXISTS phases (
            phase_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            name TEXT NOT NULL,
            state TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(project_id, run_id, phase_id),
            UNIQUE(run_id, ordinal),
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id) REFERENCES runs(project_id, run_id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            state TEXT NOT NULL,
            task_kind TEXT,
            retry_class TEXT,
            depends_on_json TEXT NOT NULL,
            latest_attempt_id TEXT,
            completed_at TEXT,
            UNIQUE(project_id, run_id, phase_id, task_id),
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id, phase_id) REFERENCES phases(project_id, run_id, phase_id)
        );

        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            worker_id TEXT,
            lease_id TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            state TEXT NOT NULL,
            checkpoint_sequence INTEGER,
            artifact_id TEXT,
            validation_id TEXT,
            UNIQUE(project_id, run_id, phase_id, task_id, attempt_id),
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id)
                REFERENCES tasks(project_id, run_id, phase_id, task_id)
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            task_id TEXT,
            attempt_id TEXT,
            sequence INTEGER NOT NULL,
            checkpoint_kind TEXT NOT NULL,
            workspace_evidence_identity TEXT,
            workspace_evidence_hash TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id) REFERENCES runs(project_id, run_id),
            FOREIGN KEY(project_id, run_id, phase_id) REFERENCES phases(project_id, run_id, phase_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id)
                REFERENCES tasks(project_id, run_id, phase_id, task_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id, attempt_id)
                REFERENCES attempts(project_id, run_id, phase_id, task_id, attempt_id)
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            reference TEXT NOT NULL,
            identity TEXT NOT NULL,
            checksum TEXT,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id)
                REFERENCES tasks(project_id, run_id, phase_id, task_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id, attempt_id)
                REFERENCES attempts(project_id, run_id, phase_id, task_id, attempt_id)
        );

        CREATE TABLE IF NOT EXISTS validations (
            validation_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            artifact_id TEXT,
            checkpoint_sequence INTEGER NOT NULL,
            state TEXT NOT NULL,
            validated_at TEXT,
            evidence_hash TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id)
                REFERENCES tasks(project_id, run_id, phase_id, task_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id, attempt_id)
                REFERENCES attempts(project_id, run_id, phase_id, task_id, attempt_id),
            FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
        );

        CREATE TABLE IF NOT EXISTS lease_bindings (
            lease_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            worker_id TEXT,
            bound_at TEXT NOT NULL,
            released_at TEXT,
            state TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id, attempt_id)
                REFERENCES attempts(project_id, run_id, phase_id, task_id, attempt_id)
        );

        CREATE TABLE IF NOT EXISTS recovery_operations (
            operation_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT,
            task_id TEXT,
            attempt_id TEXT,
            operation_kind TEXT NOT NULL,
            state TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            effect_reference TEXT,
            effect_hash TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id) REFERENCES runs(project_id, run_id),
            FOREIGN KEY(project_id, run_id, phase_id) REFERENCES phases(project_id, run_id, phase_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id)
                REFERENCES tasks(project_id, run_id, phase_id, task_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id, attempt_id)
                REFERENCES attempts(project_id, run_id, phase_id, task_id, attempt_id)
        );

        CREATE TABLE IF NOT EXISTS workspace_evidence (
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            change_kind TEXT NOT NULL,
            expected_before_identity TEXT,
            observed_before_identity TEXT,
            expected_after_identity TEXT,
            observed_after_identity TEXT,
            observed_state TEXT NOT NULL,
            checkpoint_id TEXT,
            artifact_id TEXT,
            evidence_created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id, phase_id, task_id, attempt_id)
                REFERENCES attempts(project_id, run_id, phase_id, task_id, attempt_id),
            FOREIGN KEY(checkpoint_id) REFERENCES checkpoints(checkpoint_id),
            FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
        );

        CREATE TABLE IF NOT EXISTS execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            previous_event_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            UNIQUE(project_id, run_id, sequence),
            FOREIGN KEY(project_id) REFERENCES projects(project_id),
            FOREIGN KEY(project_id, run_id) REFERENCES runs(project_id, run_id)
        );
        """
        with self._lock:
            self._connection.executescript(schema)
            row = self._connection.execute("SELECT schema_version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                self._connection.execute("INSERT INTO schema_meta(schema_version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row[0]) != SCHEMA_VERSION:
                raise IntegrityError("Unsupported execution state schema version")

    def create_project(self, *, workspace_root: Path, project_id: Optional[str] = None) -> str:
        project_id = project_id or uuid.uuid4().hex
        root = str(Path(workspace_root).resolve())
        if not root:
            raise ValueError("workspace_root must not be empty")
        with self._transaction() as conn:
            try:
                conn.execute(
                    "INSERT INTO projects(project_id, workspace_root, created_at, state) VALUES(?,?,?,?)",
                    (project_id, root, utc_now(), "ACTIVE"),
                )
            except sqlite3.IntegrityError as exc:
                raise LineageError("Project identity or workspace binding already exists") from exc
        return project_id

    def create_run(self, project_id: str, *, run_id: Optional[str] = None) -> RunRecord:
        run_id = run_id or uuid.uuid4().hex
        now = utc_now()
        with self._transaction() as conn:
            self._require_project(conn, project_id)
            conn.execute(
                "INSERT INTO runs(run_id, project_id, created_at, state, sequence, current_phase_id, current_task_id, last_checkpoint_seq, last_trusted_at, recovery_state, recovery_started_at, recovery_sequence, delivery_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, project_id, now, "CREATED", 0, None, None, None, None, "NONE", None, 0, "DELIVERY_PENDING"),
            )
            self._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=1,
                event_type="RUN_CREATED",
                entity_type="run",
                entity_id=run_id,
                payload={"project_id": project_id},
            )
            conn.execute("UPDATE runs SET sequence=? WHERE run_id=?", (1, run_id))
        return self.get_run(run_id, project_id=project_id)

    def get_run(self, run_id: str, *, project_id: Optional[str] = None) -> RunRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE run_id=?" + (" AND project_id=?" if project_id else ""),
                (run_id, project_id) if project_id else (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunRecord(
            run_id=row["run_id"],
            project_id=row["project_id"],
            state=row["state"],
            sequence=int(row["sequence"]),
            current_phase_id=row["current_phase_id"],
            current_task_id=row["current_task_id"],
            last_checkpoint_seq=row["last_checkpoint_seq"],
            last_trusted_at=row["last_trusted_at"],
            recovery_state=row["recovery_state"],
            recovery_started_at=row["recovery_started_at"],
            recovery_sequence=int(row["recovery_sequence"]),
            delivery_state=row["delivery_state"],
        )

    def transition_run(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_sequence: int,
        new_state: str,
        event_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
        current_phase_id: Optional[str] = None,
        current_task_id: Optional[str] = None,
        recovery_state: Optional[str] = None,
        delivery_state: Optional[str] = None,
    ) -> RunRecord:
        if new_state not in RUN_STATES:
            raise InvalidTransitionError(f"Unknown run state: {new_state}")
        with self._transaction() as conn:
            row = self._require_run(conn, project_id, run_id)
            actual_sequence = int(row["sequence"])
            if actual_sequence != expected_sequence:
                raise StateConflictError(
                    f"Run {run_id!r} sequence fence mismatch: expected {expected_sequence}, actual {actual_sequence}"
                )
            current_state = str(row["state"])
            allowed = _ALLOWED_TRANSITIONS["run"].get(current_state, set())
            if new_state == current_state or new_state not in allowed:
                raise InvalidTransitionError(
                    f"Forbidden run transition: {current_state} -> {new_state}"
                )
            next_sequence = expected_sequence + 1
            event_type = event_type or new_state
            self._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=event_type,
                entity_type="run",
                entity_id=entity_id or run_id,
                payload=payload or {"state": new_state},
            )
            updates = {
                "state": new_state,
                "sequence": next_sequence,
                "current_phase_id": current_phase_id if current_phase_id is not None else row["current_phase_id"],
                "current_task_id": current_task_id if current_task_id is not None else row["current_task_id"],
                "recovery_state": recovery_state if recovery_state is not None else row["recovery_state"],
                "delivery_state": delivery_state if delivery_state is not None else row["delivery_state"],
            }
            if new_state == "RECOVERING":
                updates["recovery_started_at"] = utc_now()
                updates["recovery_sequence"] = next_sequence
            if new_state in {"READY_TO_RESUME", "COMPLETED"}:
                updates["last_trusted_at"] = utc_now()
            conn.execute(
                "UPDATE runs SET state=:state, sequence=:sequence, current_phase_id=:current_phase_id, current_task_id=:current_task_id, recovery_state=:recovery_state, delivery_state=:delivery_state, recovery_started_at=COALESCE(:recovery_started_at, recovery_started_at), recovery_sequence=COALESCE(:recovery_sequence, recovery_sequence), last_trusted_at=COALESCE(:last_trusted_at, last_trusted_at) WHERE project_id=:project_id AND run_id=:run_id",
                {
                    **updates,
                    "recovery_started_at": updates.get("recovery_started_at"),
                    "recovery_sequence": updates.get("recovery_sequence"),
                    "last_trusted_at": updates.get("last_trusted_at"),
                    "project_id": project_id,
                    "run_id": run_id,
                },
            )
        return self.get_run(run_id, project_id=project_id)

    def create_phase(self, *, project_id: str, run_id: str, phase_id: str, ordinal: int, name: str) -> None:
        with self._transaction() as conn:
            self._require_run(conn, project_id, run_id)
            conn.execute(
                "INSERT INTO phases(phase_id, project_id, run_id, ordinal, name, state) VALUES(?,?,?,?,?,?)",
                (phase_id, project_id, run_id, ordinal, name, "PENDING"),
            )

    def create_task(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        task_kind: Optional[str] = None,
        retry_class: Optional[str] = None,
        depends_on: Iterable[str] = (),
    ) -> None:
        dependencies = list(depends_on)
        with self._transaction() as conn:
            self._require_phase(conn, project_id, run_id, phase_id)
            conn.execute(
                "INSERT INTO tasks(task_id, project_id, run_id, phase_id, state, task_kind, retry_class, depends_on_json, latest_attempt_id, completed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (task_id, project_id, run_id, phase_id, "PENDING", task_kind, retry_class, _canonical_json(dependencies), None, None),
            )

    def create_attempt(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        attempt_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        lease_id: Optional[str] = None,
    ) -> str:
        attempt_id = attempt_id or uuid.uuid4().hex
        with self._transaction() as conn:
            self._require_task(conn, project_id, run_id, phase_id, task_id)
            conn.execute(
                "INSERT INTO attempts(attempt_id, project_id, run_id, phase_id, task_id, worker_id, lease_id, started_at, state) VALUES(?,?,?,?,?,?,?,?,?)",
                (attempt_id, project_id, run_id, phase_id, task_id, worker_id, lease_id, utc_now(), "STARTED"),
            )
            conn.execute(
                "UPDATE tasks SET latest_attempt_id=?, state=? WHERE task_id=? AND run_id=? AND phase_id=? AND project_id=?",
                (attempt_id, "IN_PROGRESS", task_id, run_id, phase_id, project_id),
            )
        return attempt_id

    def record_workspace_evidence(self, evidence: WorkspaceEvidence) -> int:
        if evidence.change_kind not in {"CREATED", "MODIFIED", "DELETED"}:
            raise ValueError("Unsupported workspace change_kind")
        if evidence.observed_state not in {"PRESENT_COMPLETE", "PRESENT_PARTIAL", "ABSENT", "MISMATCH", "AMBIGUOUS"}:
            raise ValueError("Unsupported workspace observed_state")
        with self._transaction() as conn:
            self._require_attempt(
                conn,
                evidence.project_id,
                evidence.run_id,
                evidence.phase_id,
                evidence.task_id,
                evidence.attempt_id,
            )
            checkpoint_id = evidence.checkpoint_id
            artifact_id = evidence.artifact_id
            if checkpoint_id is not None:
                self._require_checkpoint(conn, checkpoint_id)
            if artifact_id is not None:
                self._require_artifact(conn, artifact_id)
            cursor = conn.execute(
                "INSERT INTO workspace_evidence(project_id, run_id, phase_id, task_id, attempt_id, relative_path, change_kind, expected_before_identity, observed_before_identity, expected_after_identity, observed_after_identity, observed_state, checkpoint_id, artifact_id, evidence_created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence.project_id,
                    evidence.run_id,
                    evidence.phase_id,
                    evidence.task_id,
                    evidence.attempt_id,
                    evidence.relative_path,
                    evidence.change_kind,
                    evidence.expected_before_identity,
                    evidence.observed_before_identity,
                    evidence.expected_after_identity,
                    evidence.observed_after_identity,
                    evidence.observed_state,
                    checkpoint_id,
                    artifact_id,
                    evidence.evidence_created_at,
                ),
            )
            return int(cursor.lastrowid)

    def create_recovery_operation(
        self,
        *,
        project_id: str,
        run_id: str,
        operation_kind: str,
        idempotency_key: str,
        phase_id: Optional[str] = None,
        task_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
    ) -> tuple[str, bool]:
        """Return (operation_id, created). Existing key is never duplicated."""
        with self._transaction() as conn:
            self._require_run(conn, project_id, run_id)
            if phase_id is not None:
                self._require_phase(conn, project_id, run_id, phase_id)
            if task_id is not None:
                if phase_id is None:
                    raise LineageError("task recovery binding requires phase_id")
                self._require_task(conn, project_id, run_id, phase_id, task_id)
            if attempt_id is not None:
                if phase_id is None or task_id is None:
                    raise LineageError("attempt recovery binding requires phase_id and task_id")
                self._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            existing = conn.execute(
                "SELECT operation_id FROM recovery_operations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return str(existing[0]), False
            operation_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO recovery_operations(operation_id, idempotency_key, project_id, run_id, phase_id, task_id, attempt_id, operation_kind, state) VALUES(?,?,?,?,?,?,?,?,?)",
                (operation_id, idempotency_key, project_id, run_id, phase_id, task_id, attempt_id, operation_kind, "PLANNED"),
            )
            return operation_id, True

    def get_events(self, *, project_id: str, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM execution_events WHERE project_id=? AND run_id=? ORDER BY sequence",
                (project_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_integrity(self, *, project_id: str, run_id: str) -> None:
        with self._lock:
            self._require_run(self._connection, project_id, run_id)
            rows = self._connection.execute(
                "SELECT * FROM execution_events WHERE project_id=? AND run_id=? ORDER BY sequence",
                (project_id, run_id),
            ).fetchall()
            run = self._require_run(self._connection, project_id, run_id)
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        for row in rows:
            sequence = int(row["sequence"])
            if sequence != expected_sequence:
                raise IntegrityError(f"Event sequence gap/duplicate at {sequence}; expected {expected_sequence}")
            if str(row["previous_event_hash"]) != previous_hash:
                raise IntegrityError(f"Broken previous_event_hash at sequence {sequence}")
            computed = event_hash(
                run_id=run_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                entity_type=str(row["entity_type"]),
                entity_id=str(row["entity_id"]),
                payload_hash_value=str(row["payload_hash"]),
                previous_event_hash=previous_hash,
            )
            if computed != str(row["event_hash"]):
                raise IntegrityError(f"Broken event_hash at sequence {sequence}")
            payload = json.loads(str(row["payload_json"]))
            if payload_hash(payload) != str(row["payload_hash"]):
                raise IntegrityError(f"Broken payload_hash at sequence {sequence}")
            previous_hash = computed
            expected_sequence += 1
        if int(run.sequence) != len(rows):
            raise IntegrityError(
                f"Run sequence mismatch: run={run.sequence}, events={len(rows)}"
            )
        if rows and previous_hash != str(rows[-1]["event_hash"]):
            raise IntegrityError("Latest event hash does not match chain head")

    def _append_event_tx(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        run_id: str,
        sequence: int,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        prior = conn.execute(
            "SELECT event_hash FROM execution_events WHERE project_id=? AND run_id=? ORDER BY sequence DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
        previous = str(prior[0]) if prior is not None else GENESIS_HASH
        p_hash = payload_hash(payload)
        e_hash = event_hash(
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_hash_value=p_hash,
            previous_event_hash=previous,
        )
        conn.execute(
            "INSERT INTO execution_events(project_id, run_id, sequence, event_type, entity_type, entity_id, created_at, payload_json, payload_hash, previous_event_hash, event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                run_id,
                sequence,
                event_type,
                entity_type,
                entity_id,
                utc_now(),
                _canonical_json(dict(payload)),
                p_hash,
                previous,
                e_hash,
            ),
        )

    def _require_project(self, conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise LineageError(f"Unknown project: {project_id}")
        return row

    def _require_run(self, conn: sqlite3.Connection, project_id: str, run_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM runs WHERE project_id=? AND run_id=?",
            (project_id, run_id),
        ).fetchone()
        if row is None:
            raise LineageError(f"Run {run_id!r} does not belong to project {project_id!r}")
        return row

    def _require_phase(self, conn: sqlite3.Connection, project_id: str, run_id: str, phase_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM phases WHERE project_id=? AND run_id=? AND phase_id=?",
            (project_id, run_id, phase_id),
        ).fetchone()
        if row is None:
            raise LineageError(f"Phase {phase_id!r} does not belong to run {run_id!r}")
        return row

    def _require_task(self, conn: sqlite3.Connection, project_id: str, run_id: str, phase_id: str, task_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?",
            (project_id, run_id, phase_id, task_id),
        ).fetchone()
        if row is None:
            raise LineageError(f"Task {task_id!r} does not belong to the requested execution lineage")
        return row

    def _require_attempt(self, conn: sqlite3.Connection, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM attempts WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?",
            (project_id, run_id, phase_id, task_id, attempt_id),
        ).fetchone()
        if row is None:
            raise LineageError(f"Attempt {attempt_id!r} does not belong to the requested task lineage")
        return row

    def _require_checkpoint(self, conn: sqlite3.Connection, checkpoint_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        if row is None:
            raise LineageError(f"Unknown checkpoint: {checkpoint_id}")
        return row

    def _require_artifact(self, conn: sqlite3.Connection, artifact_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if row is None:
            raise LineageError(f"Unknown artifact: {artifact_id}")
        return row

    class _Transaction:
        def __init__(self, outer: "DurableExecutionState") -> None:
            self.outer = outer

        def __enter__(self) -> sqlite3.Connection:
            self.outer._lock.acquire()
            try:
                self.outer._connection.execute("BEGIN IMMEDIATE")
                return self.outer._connection
            except Exception:
                self.outer._lock.release()
                raise

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            try:
                self.outer._connection.execute("ROLLBACK" if exc_type else "COMMIT")
            finally:
                self.outer._lock.release()

    def _transaction(self) -> _Transaction:
        return self._Transaction(self)


__all__ = [
    "SCHEMA_VERSION",
    "DurableExecutionState",
    "DurableExecutionStateError",
    "IntegrityError",
    "InvalidTransitionError",
    "LineageError",
    "RecoveryAmbiguityError",
    "RunRecord",
    "StateConflictError",
    "WorkspaceEvidence",
    "utc_now",
]
