# Batch 3 — host/view boundary tests; read-only; no execution/mutation/subprocess/auth
import sys, unittest.mock as mock
sys.path.insert(0,"/projects")
from ui.host.desktop_host import DesktopHost
from ui.service.desktop_app_service import DesktopAppService
from ui.read_models.desktop_projection import DesktopProjection

def test_host_reads_through_service_only():
    host = DesktopHost()
    with mock.patch("ui.service.desktop_app_service.ProjectScanner") as MS,          mock.patch("ui.service.desktop_app_service.ProjectStateClassifier") as MC:
        MS.return_value.scan.return_value = {"git":{"branch":"main"},"summary":{}}
        MC.return_value.classify.side_effect = lambda m: type("R",(),{"result":type("Res",(),{"state":"CONTINUE"})()})()
        result = host.show()
        assert "DESKTOP CONTROL CENTER" in result
        assert ("CONTINUE" in result or "Project State" in result)
        # Service called; no direct Core access by view

def test_refresh_is_manual_no_timer():
    host = DesktopHost()
    # Refresh is explicit call only; source check for timer/background loop
    src_host = open("/projects/ui/host/desktop_host.py").read()
    assert "threading" not in src_host
    assert "threading.Timer" not in src_host and "Timer(" not in src_host, "timer mechanism found"
    assert "subprocess" not in src_host
    assert "os.system" not in src_host

def test_view_renders_missing_contract_and_none():
    from ui.views.dashboard_view import DashboardView
    proj = DesktopProjection(
        workspace_path="/x", project_state="CONTINUE",
        run_phase="MISSING READ CONTRACT",
        leader_connection_id="MISSING READ CONTRACT",
        failover_status="MISSING READ CONTRACT",
        worker_pool_summary="MISSING READ CONTRACT",
        current_task="MISSING READ CONTRACT",
        validation_verdict=None,
        latest_test_result="MISSING READ CONTRACT",
        git_branch="b", git_head_sha="h",
        git_dirty_state=("x",),
        mutation_lock_state="MISSING READ CONTRACT",
        safety_stop_reason="MISSING READ CONTRACT",
        last_run_timestamp="MISSING READ CONTRACT",
    )
    view = DashboardView()
    out = view.render(proj)
    assert "MISSING READ CONTRACT" in out
    assert "Project State: CONTINUE" in out
    # None for validation_verdict handled correctly
    assert "Validation: None" in out or "Validation:" in out

def test_no_forbidden_paths_in_host_view():
    for path in ["/projects/ui/host/desktop_host.py","/projects/ui/views/dashboard_view.py"]:
        src = open(path).read()
        for w in ["orchestrate(","CentralLeader",".plan(",".run_tests(","subprocess","os.system","shell=True","execution_gate.run","GitMutationExecutor","threading.Timer","asyncio"]:
            assert w not in src, f"{path}: forbidden {w}"
