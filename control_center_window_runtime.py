from __future__ import annotations

from typing import Any


_INSTALLED = "_responsive_window_runtime_installed"


def _install_scrollable_body(app: Any) -> None:
    """Replace the fixed body with a vertically scrollable content viewport."""
    old_body = app.body
    parent = old_body.master

    try:
        grid_info = dict(old_body.grid_info())
    except Exception:
        grid_info = {"row": 1, "column": 0, "sticky": "nsew", "pady": (12, 0)}

    try:
        old_body.grid_forget()
        old_body.destroy()
    except Exception:
        pass

    container = app.ttk.Frame(parent)
    container.grid(**grid_info)
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)

    canvas = app.tk.Canvas(container, highlightthickness=0, borderwidth=0)
    scrollbar = app.ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    body = app.ttk.Frame(canvas, padding=(0, 0, 8, 0))
    window_id = canvas.create_window((0, 0), window=body, anchor="nw")

    def update_scrollregion(_event: Any = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(window_id, width=max(canvas.winfo_width() - 4, 1))

    def on_canvas_configure(event: Any) -> None:
        canvas.itemconfigure(window_id, width=max(event.width - 4, 1))
        update_scrollregion()

    def on_mousewheel(event: Any) -> None:
        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            canvas.yview_scroll(delta, "units")

    body.bind("<Configure>", update_scrollregion, add="+")
    canvas.bind("<Configure>", on_canvas_configure, add="+")
    canvas.bind_all("<MouseWheel>", on_mousewheel, add="+")

    app._scroll_canvas = canvas
    app._scroll_body = body
    app.body = body
    app.body.columnconfigure(0, weight=1)
    app.body.rowconfigure(0, weight=1)


def _fit_window_to_screen(app: Any) -> None:
    """Choose a sane initial size for the actual Windows desktop resolution."""
    root = app.root
    root.update_idletasks()

    screen_width = max(root.winfo_screenwidth(), 1024)
    screen_height = max(root.winfo_screenheight(), 720)

    width = min(1380, screen_width - 40)
    height = min(880, screen_height - 80)

    width = max(width, 980)
    height = max(height, 600)

    root.geometry(f"{width}x{height}")
    root.minsize(980, 600)
    root.resizable(True, True)


def install_responsive_window(app_class: Any) -> None:
    """Add responsive sizing/scrolling without changing application authority."""
    if getattr(app_class, _INSTALLED, False):
        return

    original_init = app_class.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        current_page = getattr(self, "current_page", "Dashboard")
        _fit_window_to_screen(self)
        _install_scrollable_body(self)
        self.show(current_page)
        self.root.update_idletasks()

    app_class.__init__ = __init__
    setattr(app_class, _INSTALLED, True)
