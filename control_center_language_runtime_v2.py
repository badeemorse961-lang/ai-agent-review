from __future__ import annotations

from typing import Any

from control_center_language_runtime import install_bilingual_support as _install_base


_INSTALLED = "_bilingual_runtime_v2_installed"


def _button_text(language: str) -> str:
    return "English" if language == "ar" else "العربية"


def install_bilingual_support(app_class: Any) -> None:
    if getattr(app_class, _INSTALLED, False):
        return

    _install_base(app_class)
    base_show = app_class.show
    base_toggle = app_class.toggle_language

    def show(self: Any, page: str) -> None:
        base_show(self, page)
        button = getattr(self, "language_button", None)
        if button is not None:
            button.configure(text=_button_text(getattr(self, "language", "en")))

    def toggle_language(self: Any) -> None:
        base_toggle(self)
        button = getattr(self, "language_button", None)
        if button is not None:
            button.configure(text=_button_text(getattr(self, "language", "en")))

    app_class.show = show
    app_class.toggle_language = toggle_language
    setattr(app_class, _INSTALLED, True)
