from __future__ import annotations

from pathlib import Path

from application_boundary import ApplicationIntent, ApplicationResult, ControlCenterService


def test_application_intent_rejects_unknown_action() -> None:
    result = ControlCenterService().dispatch(ApplicationIntent("unknown", {}))
    assert result.status == "REJECTED"
    assert "Unknown application intent" in (result.error or "")


def test_project_selection_is_bounded(tmp_path: Path) -> None:
    service = ControlCenterService(autowire_core=False)
    result = service.dispatch(ApplicationIntent("select_project", {"workspace_root": str(tmp_path)}))
    assert result.status == "OK"
    assert service.workspace_root == tmp_path.resolve()


def test_project_selection_rejects_missing_path(tmp_path: Path) -> None:
    service = ControlCenterService(autowire_core=False)
    result = service.dispatch(ApplicationIntent("select_project", {"workspace_root": str(tmp_path / "missing")}))
    assert result.status == "REJECTED"


def test_chat_requires_explicit_core_runtime_dependencies(tmp_path: Path) -> None:
    service = ControlCenterService(workspace_root=tmp_path, autowire_core=False)
    result = service.dispatch(ApplicationIntent("send_leader_goal", {"goal": "inspect", "task_id": "UI-1"}))
    assert result.status == "BLOCKED"
    assert "not configured" in (result.error or "")


def test_session_evidence_does_not_render_known_credential_patterns() -> None:
    service = ControlCenterService(autowire_core=False)
    result = ApplicationResult("ERROR", {}, "Authorization: Bearer sk-or-v1-this-is-not-a-real-key")
    service._record_event(ApplicationIntent("test", {"value": "secret"}), result)
    evidence = service.dispatch(ApplicationIntent("session_evidence", {}))
    assert evidence.status == "OK"
    assert "sk-or-v1-" not in repr(evidence.data)
    assert "[REDACTED]" in repr(evidence.data)
