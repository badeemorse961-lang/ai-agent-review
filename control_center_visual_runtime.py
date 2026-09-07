from __future__ import annotations

from typing import Any


_INSTALLED = "_control_center_visual_runtime_installed"


def install_visual_runtime(app_class: Any) -> None:
    """Improve desktop navigation readability without changing application authority."""
    if getattr(app_class, _INSTALLED, False):
        return

    original_init = app_class.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        style = self.ttk.Style(self.root)
        style.configure(
            "Nav.TButton",
            anchor="center",
            justify="center",
            padding=(10, 10),
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 11, "bold"),
            padding=(12, 9),
        )

        # Keep the navigation readable even when the window is resized down.
        self.root.grid_columnconfigure(0, minsize=220)
        sidebar_items = self.root.grid_slaves(row=0, column=0)
        if sidebar_items:
            sidebar = sidebar_items[0]
            try:
                sidebar.configure(width=220)
            except Exception:
                pass
            try:
                sidebar.pack_propagate(False)
            except Exception:
                pass
            for button in sidebar.winfo_children():
                try:
                    if button.winfo_class() == "TButton":
                        button.configure(wraplength=190, justify="center")
                except Exception:
                    pass

        self.root.update_idletasks()

    app_class.__init__ = __init__
    setattr(app_class, _INSTALLED, True)
