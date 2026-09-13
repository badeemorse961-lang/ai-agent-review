# Batch 3 — thin read-only host stub. No framework, no timer, no execution.
import sys
sys.path.insert(0,"/projects")
from ui.service.desktop_app_service import DesktopAppService
from ui.views.dashboard_view import DashboardView
from ui.read_models.desktop_projection import DesktopProjection

class DesktopHost:
    def __init__(self, workspace_root: str = "/projects"):
        self.service = DesktopAppService()
        self.view = DashboardView()
        self.root = workspace_root
    def show(self) -> str:
        # Single manual projection read; no background loop
        proj = self.service.get_projection(self.root)
        return self.view.render(proj)
    def refresh_manual(self) -> str:
        # Explicit manual refresh only; replace projection
        proj = self.service.get_projection(self.root)
        return self.view.refresh(proj)
