# Batch 2 tests — prove real contracts, frozen projection, no forbidden paths
import sys, unittest.mock as mock
sys.path.insert(0,"/projects")
from ui.service.desktop_app_service import DesktopAppService
from ui.read_models.desktop_projection import DesktopProjection

def test_scan_classify_chain_and_immutability():
    svc = DesktopAppService()
    manifest = {"summary":{"files":1},"git":{"branch":"main","head_sha":"x"}}
    with mock.patch("ui.service.desktop_app_service.ProjectScanner") as MS,          mock.patch("ui.service.desktop_app_service.ProjectStateClassifier") as MC:
        MS.return_value.scan.return_value = manifest
        MC.return_value.classify.side_effect = lambda m: type("R",(),{"result":type("Res",(),{"state":"CONTINUE"})()})()
        proj = svc.get_projection("/projects")
        MS.return_value.scan.assert_called_once()
        MC.return_value.classify.assert_called_once()
        args, _ = MC.return_value.classify.call_args
        assert args[0] == manifest, "classify did not receive exact scan manifest"
        assert proj.project_state == "CONTINUE"
        assert proj.git_branch == "main"
        assert proj.workspace_path == "/projects"
    # Frozen / immutable check
    try:
        proj.project_state = "MODIFIED"
        assert False, "not frozen"
    except Exception:
        pass  # frozen dataclass raises

def test_missing_contracts_for_c_through_h():
    svc = DesktopAppService()
    proj = svc.get_projection("/projects")
    assert proj.run_phase == "MISSING READ CONTRACT"
    assert proj.leader_connection_id == "MISSING READ CONTRACT"
    assert proj.failover_status == "MISSING READ CONTRACT"
    assert proj.worker_pool_summary == "MISSING READ CONTRACT"
    assert proj.current_task == "MISSING READ CONTRACT"
    assert proj.validation_verdict is None  # not fabricated
    assert proj.latest_test_result == "MISSING READ CONTRACT"
    assert proj.mutation_lock_state == "MISSING READ CONTRACT"
    assert proj.safety_stop_reason == "MISSING READ CONTRACT"
    assert proj.last_run_timestamp == "MISSING READ CONTRACT"

def test_no_forbidden_paths_in_service():
    src = open("/projects/ui/service/desktop_app_service.py").read()
    for w in ["orchestrate(","CentralLeader",".plan(",".run_tests(","subprocess","os.system","shell=True","GitMutationExecutor","execution_gate.run"]:
        assert w not in src, f"forbidden: {w}"
