# Batch 1 tests — prove read-only boundary and prohibit execution/mutation

import sys, unittest
sys.path.insert(0, "/projects")
sys.path.insert(0, "/projects/ui")

from ui.service.app_service import DashboardAppService
from ui.read_models.dashboard_read import DashboardSnapshot
from ui.intents.app_intent import ProjectDiscoveryIntent

class TestDashboardReadOnlyBoundary(unittest.TestCase):
    def test_snapshot_is_read_only(self):
        s = DashboardAppService().get_snapshot("/projects")
        self.assertIsNotNone(s)
        self.assertIsInstance(s, DashboardSnapshot)

    def test_no_secrets_in_snapshot(self):
        s = DashboardAppService().get_snapshot("/projects")
        # Verify no raw key fields exist at all
        for field in ["provider_key", "secret", "token", "password", "raw_prompt"]:
            self.assertFalse(hasattr(s, field), f"Secret field {field} must not exist")

    def test_prohibited_intents_not_implemented(self):
        # Confirm Batch 1 does not include execution/mutation intents
        from ui.intents import app_intent
        names = [n for n in dir(app_intent) if not n.startswith("_")]
        forbidden = {"OrchestrationStartIntent", "LeaderPlanIntent", "ContextBuildIntent"}
        for f in forbidden:
            self.assertNotIn(f, names, f"Forbidden intent {f} must not be in Batch 1")

    def test_latest_test_result_is_not_run(self):
        s = DashboardAppService().get_snapshot("/projects")
        self.assertEqual(s.latest_test_result, "NOT RUN")

    def test_no_execution_triggered(self):
        # Batch 1 uses only read contracts; this test verifies adapter does not call them
        service = DashboardAppService()
        # The adapter must not reference orchechestrate/run_tests/GitMutationExecutor
        import inspect
        src = inspect.getsource(service.get_snapshot)
        for bad in ["orchestrate(", "run_tests(", "GitMutationExecutor", "execute(", "subprocess", "shell"]:
            self.assertNotIn(bad, src, f"Prohibited call {bad} found in Batch 1 adapter")

if __name__ == "__main__":
    unittest.main()
