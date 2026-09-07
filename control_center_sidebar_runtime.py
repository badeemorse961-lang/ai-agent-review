from __future__ import annotations

from typing import Any


_INSTALLED = "_scrollable_sidebar_runtime_installed"


def install_scrollable_sidebar(app_class: Any) -> None:
    """Keep the navigation accessible on short Windows displays."""
    if getattr(app_class, _INSTALLED, False):
        return

    original_init = app_class.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        root = self.root
        sidebar = root.grid_slaves(row=0, column=0)[0]
        self._cc_sidebar = sidebar

        nav_labels = {label for label, _ in self.NAVIGATION}
        nav_buttons: list[Any] = []
        fixed_controls: list[Any] = []
        for child in sidebar.winfo_children():
            try:
                text = child.cget("text")
            except Exception:
                text = ""
            if child.winfo_class() in {"TButton", "Button"} and isinstance(text, str):
                if text.strip() in nav_labels:
                    nav_buttons.append(child)
                else:
                    fixed_controls.append(child)
            else:
                try:
                    child.pack_forget()
                except Exception:
                    pass

        if len(nav_buttons) != len(self.NAVIGATION):
            return

        for child in sidebar.winfo_children():
            try:
                child.pack_forget()
            except Exception:
                pass

        self._cc_sidebar_nav = nav_buttons
        self._cc_sidebar_fixed = [
            child for child in fixed_controls if child in sidebar.winfo_children()
        ]

        scrollbar = self.ttk.Scrollbar(sidebar, orient="vertical")
        self._cc_sidebar_scrollbar = scrollbar
        scrollbar.place(relx=1.0, y=86, anchor="ne", width=14, relheight=0.77)

        self._cc_sidebar_offset = 0
        self._cc_sidebar_content_height = 0

        def set_scroll(first: float, last: float) -> None:
            scrollbar.set(first, last)

        def scroll_command(*parts: str) -> None:
            if not parts:
                return
            if parts[0] == "moveto" and len(parts) == 2:
                try:
                    fraction = min(1.0, max(0.0, float(parts[1])))
                except ValueError:
                    return
                self._cc_sidebar_offset = int(
                    (self._cc_sidebar_content_height - self._cc_sidebar_nav_height()) * fraction
                )
            elif parts[0] == "scroll" and len(parts) >= 3:
                try:
                    amount = int(parts[1])
                except ValueError:
                    return
                units = 34 if parts[2] == "units" else self._cc_sidebar_nav_height()
                max_offset = max(0, self._cc_sidebar_content_height - self._cc_sidebar_nav_height())
                self._cc_sidebar_offset = min(
                    max_offset,
                    max(0, self._cc_sidebar_offset + amount * units),
                )
            self._layout_sidebar()

        scrollbar.configure(command=scroll_command)

        def on_wheel(event: Any) -> str:
            delta = int(-event.delta / 120) if event.delta else 0
            if delta:
                scroll_command("scroll", str(delta), "units")
            return "break"

        for button in nav_buttons:
            button.bind("<MouseWheel>", on_wheel, add="+")
        sidebar.bind("<MouseWheel>", on_wheel, add="+")
        sidebar.bind("<Configure>", lambda _event: self._layout_sidebar(), add="+")

        self._cc_sidebar_set_scroll = set_scroll
        self._cc_sidebar_wheel = on_wheel
        self._layout_sidebar()

    def _sidebar_nav_height(self: Any) -> int:
        sidebar = self._cc_sidebar
        return max(160, sidebar.winfo_height() - 190)

    def _layout_sidebar(self: Any) -> None:
        sidebar = self._cc_sidebar
        width = max(160, sidebar.winfo_width())
        height = max(420, sidebar.winfo_height())
        nav_top = 88
        nav_height = max(160, height - 188)
        button_height = 38
        gap = 5
        content_height = len(self._cc_sidebar_nav) * (button_height + gap) - gap
        self._cc_sidebar_content_height = max(0, content_height)
        max_offset = max(0, content_height - nav_height)
        self._cc_sidebar_offset = min(max_offset, max(0, self._cc_sidebar_offset))

        for index, button in enumerate(self._cc_sidebar_nav):
            y = nav_top + index * (button_height + gap) - self._cc_sidebar_offset
            button.place(x=0, y=y, width=max(150, width - 14), height=button_height)

        controls = self._cc_sidebar_fixed
        control_height = 38
        control_gap = 6
        bottom = height - 8
        for button in reversed(controls):
            y = bottom - control_height
            button.place(x=0, y=y, width=max(150, width), height=control_height)
            bottom = y - control_gap

        scrollbar = self._cc_sidebar_scrollbar
        first = 0.0
        last = 1.0
        if content_height > nav_height:
            span = nav_height / content_height
            first = self._cc_sidebar_offset / content_height
            last = min(1.0, first + span)
        scrollbar.place(
            x=max(0, width - 14),
            y=nav_top,
            width=14,
            height=nav_height,
        )
        self._cc_sidebar_set_scroll(first, last)

    app_class.__init__ = __init__
    app_class._cc_sidebar_nav_height = _sidebar_nav_height
    app_class._layout_sidebar = _layout_sidebar
    setattr(app_class, _INSTALLED, True)
