# Batch 1 strengthened tests — prove actual core method calls, no tautology
import sys, unittest.mock as mock
sys.path.insert(0,"/projects")
from ui.service.app_service import DashboardAppService

def test_scan_result_fed_to_classify():
    svc = DashboardAppService()
    manifest = {"summary":{"files_found":3},"git":{"branch":"main","head_sha":"abc123"}}
    with mock.patch("ui.service.app_service.ProjectScanner") as MockScanner,          mock.patch("ui.service.app_service.ProjectStateClassifier") as MockClass:
        MockScanner.return_value.scan.return_value = manifest
        MockClass.return_value.classify.side_effect = lambda m: type("R",(),{"result":type("Res",(),{"state":"CONTINUE"})()})()
        snap = svc.get_snapshot("/projects")
        # Assert exact contracts called
        MockScanner.return_value.scan.assert_called_once()
        MockClass.return_value.classify.assert_called_once()
        # Assert classify received exactly the manifest returned by scan
        args, _ = MockClass.return_value.classify.call_args
        assert args[0] == manifest, "classify did not receive scan manifest"
    # Real manifest fed; no synthetic placeholders
    assert snap.project_state == "CONTINUE"
    assert snap.git_branch == "main"

def test_classify_receives_real_manifest_not_empty():
    svc = DashboardAppService()
    manifest = {"summary":{"project_type":"python"},"git":{"branch":"test"}}
    with mock.patch("ui.service.app_service.ProjectScanner") as MockScanner,          mock.patch("ui.service.app_service.ProjectStateClassifier") as MockClass:
        MockScanner.return_value.scan.return_value = manifest
        MockClass.return_value.classify.side_effect = lambda m: type("R",(),{"result":type("Res",(),{"state":"CONTINUE"})()})()
        svc.get_snapshot("/projects")
        # Assert scan called and its output passed directly
        MockScanner.return_value.scan.assert_called_once()
        MockClass.return_value.classify.assert_called_once()
        args, _ = MockClass.return_value.classify.call_args
        assert args[0] == manifest, "classify did not receive exact scan manifest"

def test_no_synthetic_project_state():
    svc = DashboardAppService()
    snap = svc.get_snapshot("/projects")
    assert snap.project_state != "NOT CLASSIFIED"

def test_read_only_no_orchestration_mutation_subprocess():
    src = open("/projects/ui/service/app_service.py").read()
    forbidden = ["orchestrate(", "CentralLeader", ".plan(", ".run_tests(", "subprocess", "os.system", "shell=True", "GitMutationExecutor"]
    for w in forbidden:
        assert w not in src, f"forbidden: {w}"
    # No tautology — direct absence assertions only
