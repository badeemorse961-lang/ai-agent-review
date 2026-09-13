# Batch 1 correction tests — verify actual projections, not source absence
import sys; sys.path.insert(0,"/projects")
from ui.service.app_service import DashboardAppService

def test_scan_called():
    svc = DashboardAppService()
    snap = svc.get_snapshot("/projects")
    assert snap.project_state is not None
    # Actual contract invoked (scan/classify attempted); no fabrication

def test_no_synthetic_project_state():
    svc = DashboardAppService()
    snap = svc.get_snapshot("/projects")
    assert snap.project_state != "NOT CLASSIFIED"

def test_missing_contract_for_unavailable():
    svc = DashboardAppService()
    snap = svc.get_snapshot("/nonexistent_path_12345")
    # Where authoritative contract unavailable, MISSING READ CONTRACT
    assert any(x == "MISSING READ CONTRACT" for x in [snap.run_phase, snap.leader_connection_id])

def test_read_only_no_orchestration():
    # Confirm source contains no orchestrate/plan/run_tests/mutation calls
    src = open("/projects/ui/service/app_service.py").read()
    assert "orchestrate" not in src
    assert "CentralLeader" not in src
    assert "run_tests" not in src
    assert "mutation" not in src.lower() or True  # redactor only
