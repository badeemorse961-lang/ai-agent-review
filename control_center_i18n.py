from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_INSTALLED = "_bilingual_i18n_installed"
_SOURCE_TEXT = "_bilingual_source_text"
_SOURCE_HEADINGS = "_bilingual_source_headings"

_TRANSLATIONS = {
    "AI-Agent": "وكيل الذكاء الاصطناعي",
    "Control Center": "مركز التحكم",
    "Dashboard": "لوحة المتابعة",
    "Chat": "المحادثة",
    "Projects": "المشاريع",
    "Connections & Pools": "الاتصالات والمجموعات",
    "Workers": "العُمّال",
    "Run / Plan": "التشغيل / الخطة",
    "Evidence & Activity": "الأدلة والنشاط",
    "Git & Changes": "Git والتغييرات",
    "Tests & Verification": "الاختبارات والتحقق",
    "Safety & Policy": "السلامة والسياسات",
    "Settings / Diagnostics": "الإعدادات / التشخيص",
    "Overview": "نظرة عامة",
    "Leader": "القائد",
    "Workspace": "مساحة العمل",
    "Connections": "الاتصالات",
    "Fleet": "الأسطول",
    "Run": "التشغيل",
    "Evidence": "الأدلة",
    "Git": "Git",
    "Tests": "الاختبارات",
    "Safety": "السلامة",
    "Settings": "الإعدادات",
    "Toggle theme": "تبديل المظهر",
    "Exit": "خروج",
    "Operational state derived from the Core; no simulated runtime data.": "الحالة التشغيلية مستمدة من النواة؛ لا توجد بيانات تشغيلية وهمية.",
    "Chat with Central Leader": "المحادثة مع القائد المركزي",
    "Natural-language goals become typed application intents; they are never shell commands.": "الأهداف باللغة الطبيعية تتحول إلى نوايا تطبيقية مهيكلة، وليست أوامر Shell.",
    "New Goal": "هدف جديد",
    "Goal": "الهدف",
    "Task ID": "معرّف المهمة",
    "Send Goal": "إرسال الهدف",
    "Leader Response": "استجابة القائد",
    "Goal accepted": "تم قبول الهدف",
    "Tasks": "المهام",
    "Select a bounded workspace; the Core remains responsible for project classification.": "اختر مساحة عمل محددة؛ وتبقى النواة مسؤولة عن تصنيف المشروع.",
    "Active Workspace": "مساحة العمل النشطة",
    "Workspace path": "مسار مساحة العمل",
    "Select": "اختيار",
    "Project State": "حالة المشروع",
    "Project state, detected documentation, health, conflicts, and gaps are read from the Core project-understanding pipeline.": "حالة المشروع والوثائق المكتشفة والصحة والتعارضات والفجوات تُقرأ من مسار فهم المشروع في النواة.",
    "Registry assignments are authoritative; runtime health is observational.": "تعيينات السجل هي المرجع الموثوق؛ وصحة التشغيل حالة رصدية.",
    "Refresh": "تحديث",
    "Connection ID": "معرّف الاتصال",
    "Provider": "المزوّد",
    "Model": "النموذج",
    "Assignment": "التعيين",
    "Runtime": "التشغيل",
    "Metadata": "البيانات الوصفية",
    "Fingerprint": "البصمة",
    "Import openrouter source": "استيراد مصدر OpenRouter",
    "Import groq source": "استيراد مصدر Groq",
    "Imported": "تم الاستيراد",
    "Workers / Fleet": "العُمّال / الأسطول",
    "Router-owned health, leases, and availability; the UI adds no worker authority.": "الصحة والتأجير والتوافر مملوكة للموجّه؛ ولا تضيف الواجهة أي صلاحية للعمّال.",
    "Healthy": "سليم",
    "Failed": "فاشل",
    "Leased": "مؤجّر",
    "available": "متاح",
    "runtime/external": "التشغيل / خارجي",
    "active task leases": "تأجيرات المهام النشطة",
    "Active Leases": "التأجيرات النشطة",
    "Task": "المهمة",
    "Worker": "العامل",
    "Role": "الدور",
    "Standby": "احتياطي",
    "Execution remains exclusively owned by the canonical Core runtime.": "يبقى التنفيذ مملوكًا حصريًا لوقت تشغيل النواة القياسي.",
    "Canonical Run": "التشغيل القياسي",
    "Run Task": "تشغيل المهمة",
    "Run Evidence": "أدلة التشغيل",
    "Canonical run completed.": "اكتمل التشغيل القياسي.",
    "Last run from this session:": "آخر تشغيل في هذه الجلسة:",
    "Task records:": "سجلات المهام:",
    "Structured application events, redacted before display.": "أحداث التطبيق المهيكلة بعد تنقيحها قبل العرض.",
    "Inspection-only application view. Mutation authority remains in the existing Git control plane.": "عرض فحص فقط. وتبقى صلاحية التعديل في مسار تحكم Git الحالي.",
    "Repository": "المستودع",
    "Branch": "الفرع",
    "HEAD": "HEAD",
    "Worktree": "شجرة العمل",
    "Authority": "الصلاحية",
    "The UI distinguishes evidence states and never invents results.": "تميّز الواجهة بين حالات الأدلة ولا تختلق النتائج.",
    "Compile": "الترجمة",
    "Focused tests": "الاختبارات المركزة",
    "Full regression": "الاختبار الشامل",
    "Security audit": "تدقيق الأمان",
    "Provider smoke": "اختبار المزوّد",
    "Local credential environment required": "يلزم إعداد بيانات اعتماد محلية",
    "Windows E2E": "اختبار Windows الشامل",
    "Reported by CI / Windows acceptance": "مبلغ عنه بواسطة CI / قبول Windows",
    "Pending current UI promotion gate": "بانتظار بوابة ترقية الواجهة الحالية",
    "Evidence is read-only on this surface": "الأدلة للقراءة فقط في هذه الواجهة",
    "The Control Center explains policy; it cannot override it.": "مركز التحكم يشرح السياسات ولا يمكنه تجاوزها.",
    "Core Safety Invariants": "ثوابت أمان النواة",
    "Current Safety Evidence": "دليل السلامة الحالي",
    "Reason": "السبب",
    "Affected task/run": "المهمة / التشغيل المتأثر",
    "Event data": "بيانات الحدث",
    "Recovery": "الاستعادة",
    "No SAFE_STOP / BLOCKED event recorded in this session.": "لا يوجد حدث SAFE_STOP / BLOCKED مسجل في هذه الجلسة.",
    "Resolve the Core evidence/authorization condition before retrying; no UI bypass is available.": "عالج شرط الأدلة/التفويض في النواة قبل إعادة المحاولة؛ لا يوجد تجاوز من الواجهة.",
    "UNKNOWN / CONFLICT": "UNKNOWN / CONFLICT",
    "SAFE_STOP; autonomous execution is blocked": "SAFE_STOP؛ التنفيذ الذاتي محظور",
    "Model output": "مخرجات النموذج",
    "Untrusted input; validated before authority is granted": "مدخل غير موثوق؛ تتم مراجعته قبل منح الصلاحية",
    "Mutation": "التعديل",
    "Independent validation + authorization + checkpoint required": "يلزم تحقق مستقل + تفويض + نقطة تحقق",
    "Git terminal": "طرفية Git",
    "Inspection-only; mutation uses the dedicated control plane": "فحص فقط؛ التعديل يستخدم مسار التحكم المخصص",
    "Secrets": "الأسرار",
    "Redacted before UI activity/evidence and never rendered after import": "تُنقح قبل نشاط/أدلة الواجهة ولا تُعرض بعد الاستيراد",
    "Non-secret application and runtime information.": "معلومات التطبيق ووقت التشغيل غير الحساسة.",
    "Environment": "البيئة",
    "Application": "التطبيق",
    "Python": "Python",
    "Platform": "المنصة",
    "Credentials rendered": "عرض بيانات الاعتماد",
    "NO": "لا",
    "Application authority": "صلاحية التطبيق",
    "typed intents over Core": "نوايا مهيكلة فوق النواة",
    "Dashboard refreshed": "تم تحديث لوحة المتابعة",
    "Project selected": "تم اختيار المشروع",
    "Connection registry refreshed": "تم تحديث سجل الاتصالات",
    "Worker fleet refreshed": "تم تحديث أسطول العمّال",
    "Evidence refreshed": "تم تحديث الأدلة",
    "Git snapshot refreshed": "تم تحديث لقطة Git",
    "Safety evidence refreshed": "تم تحديث دليل السلامة",
    "Leader plan received": "تم استلام خطة القائد",
}


def _translate(source: str, language: str) -> str:
    if language == "en":
        return source
    return _TRANSLATIONS.get(source, source)


def _remember_source(widget: Any, value: str) -> str:
    source = getattr(widget, _SOURCE_TEXT, None)
    if not isinstance(source, str):
        setattr(widget, _SOURCE_TEXT, value)
        source = value
    return source


def _apply_widget_language(widget: Any, language: str) -> None:
    try:
        widget_class = widget.winfo_class()
    except Exception:
        return

    if widget_class in {"TButton", "Button", "TLabel", "Label", "TLabelFrame", "Labelframe"}:
        try:
            value = widget.cget("text")
            if isinstance(value, str):
                prefix = value[: len(value) - len(value.lstrip())]
                source = _remember_source(widget, value.strip())
                widget.configure(text=prefix + _translate(source, language))
                widget.configure(anchor="e" if language == "ar" else "w")
                if widget_class in {"TLabel", "Label"}:
                    widget.configure(justify="right" if language == "ar" else "left")
        except Exception:
            pass

    if widget_class in {"TEntry", "Entry"}:
        try:
            widget.configure(justify="right" if language == "ar" else "left")
        except Exception:
            pass

    if widget_class == "Text":
        try:
            widget.configure(justify="right" if language == "ar" else "left")
        except Exception:
            pass

    if widget_class == "Treeview":
        try:
            sources = getattr(widget, _SOURCE_HEADINGS, {})
            for column in widget["columns"]:
                current = widget.heading(column, "text")
                if column not in sources:
                    sources[column] = current if isinstance(current, str) else ""
                source = sources[column]
                widget.heading(column, text=_translate(source, language))
                widget.column(column, anchor="e" if language == "ar" else "w")
            setattr(widget, _SOURCE_HEADINGS, sources)
        except Exception:
            pass

    try:
        for child in widget.winfo_children():
            _apply_widget_language(child, language)
    except Exception:
        pass


def install_bilingual_support(app_class: Any) -> None:
    """Install reversible English/Arabic presentation switching."""
    if getattr(app_class, _INSTALLED, False):
        return

    original_init = app_class.__init__
    original_show = app_class.show

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        self.language = "en"
        original_init(self, *args, **kwargs)
        sidebar_items = self.root.grid_slaves(row=0, column=0)
        if sidebar_items:
            sidebar = sidebar_items[0]
            self.language_button = self.ttk.Button(
                sidebar,
                text="العربية",
                command=self.toggle_language,
            )
            self.language_button.pack(fill="x", pady=2)

    def show(self: Any, page: str) -> None:
        original_show(self, page)
        self._apply_bilingual_language()

    def toggle_language(self: Any) -> None:
        self.language = "ar" if self.language == "en" else "en"
        self._apply_bilingual_language()

    def _apply_bilingual_language(self: Any) -> None:
        _apply_widget_language(self.root, self.language)
        if hasattr(self, "language_button"):
            self.language_button.configure(
                text="English" if self.language == "ar" else "العربية"
            )

    app_class.__init__ = __init__
    app_class.show = show
    app_class.toggle_language = toggle_language
    app_class._apply_bilingual_language = _apply_bilingual_language
    setattr(app_class, _INSTALLED, True)
