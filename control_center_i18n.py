from __future__ import annotations

from typing import Any


_INSTALLED = "_bilingual_i18n_installed"

_TRANSLATIONS = {
    "AI-Agent": "الوكيل الذكي",
    "Control Center": "مركز التحكم",
    "Dashboard": "لوحة المعلومات",
    "Chat": "الدردشة",
    "Projects": "المشاريع",
    "Connections & Pools": "الاتصالات والمجموعات",
    "Workers": "العمال",
    "Run / Plan": "التنفيذ / الخطة",
    "Evidence & Activity": "الأدلة والنشاط",
    "Git & Changes": "Git والتغييرات",
    "Tests & Verification": "الاختبارات والتحقق",
    "Safety & Policy": "الأمان والسياسات",
    "Settings / Diagnostics": "الإعدادات / التشخيص",
    "Overview": "نظرة عامة",
    "Leader": "القائد",
    "Workspace": "مساحة العمل",
    "Connections": "الاتصالات",
    "Fleet": "الأسطول",
    "Run": "التنفيذ",
    "Evidence": "الأدلة",
    "Git": "Git",
    "Tests": "الاختبارات",
    "Safety": "الأمان",
    "Settings": "الإعدادات",
    "Toggle theme": "تبديل المظهر",
    "Exit": "خروج",
    "Toggle language": "تبديل اللغة",
    "English": "الإنجليزية",
    "Arabic": "العربية",
    "Operational state derived from the Core; no simulated runtime data.": "الحالة التشغيلية مستمدة من الـCore؛ لا توجد بيانات تشغيلية وهمية.",
    "Chat with Central Leader": "الدردشة مع القائد المركزي",
    "Natural-language goals become typed application intents; they are never shell commands.": "الأهداف بلغة طبيعية تتحول إلى نوايا تطبيق typed؛ ولا تصبح أوامر shell أبدًا.",
    "New Goal": "هدف جديد",
    "Goal": "الهدف",
    "Task ID": "معرّف المهمة",
    "Send Goal": "إرسال الهدف",
    "Leader Response": "استجابة القائد",
    "Goal accepted": "تم قبول الهدف",
    "Tasks": "المهام",
    "Select a bounded workspace; the Core remains responsible for project classification.": "اختر مساحة عمل محددة؛ ويظل الـCore مسؤولًا عن تصنيف المشروع.",
    "Active Workspace": "مساحة العمل النشطة",
    "Workspace path": "مسار مساحة العمل",
    "Select": "اختيار",
    "Project State": "حالة المشروع",
    "Project state, detected documentation, health, conflicts, and gaps are read from the Core project-understanding pipeline.": "تُقرأ حالة المشروع والوثائق المكتشفة والصحة والتعارضات والفجوات من مسار فهم المشروع في الـCore.",
    "Registry assignments are authoritative; runtime health is observational.": "تعيينات السجل هي المرجع الموثوق؛ وصحة التشغيل للمراقبة فقط.",
    "Refresh": "تحديث",
    "Connection ID": "معرّف الاتصال",
    "Provider": "المزوّد",
    "Model": "النموذج",
    "Assignment": "التعيين",
    "Runtime": "وقت التشغيل",
    "Metadata": "البيانات الوصفية",
    "Fingerprint": "البصمة",
    "Import openrouter source": "استيراد مصدر OpenRouter",
    "Import groq source": "استيراد مصدر Groq",
    "Imported": "تم الاستيراد",
    "Workers / Fleet": "العمال / الأسطول",
    "Router-owned health, leases, and availability; the UI adds no worker authority.": "الصحة والتأجير والتوافر مملوكة للموجّه؛ ولا تضيف الواجهة أي صلاحية للعمال.",
    "Healthy": "سليم",
    "Failed": "فاشل",
    "Leased": "مؤجّر",
    "available": "متاح",
    "runtime/external": "وقت التشغيل / خارجي",
    "active task leases": "عقود مهام نشطة",
    "Active Leases": "عقود التأجير النشطة",
    "Task": "المهمة",
    "Worker": "العامل",
    "Role": "الدور",
    "Standby": "احتياطي",
    "Execution remains exclusively owned by the canonical Core runtime.": "يبقى التنفيذ مملوكًا حصريًا لوقت تشغيل الـCore المعياري.",
    "Canonical Run": "التنفيذ المعياري",
    "Run Task": "تنفيذ المهمة",
    "Run Evidence": "أدلة التنفيذ",
    "Canonical run completed.": "اكتمل التنفيذ المعياري.",
    "Evidence & Activity": "الأدلة والنشاط",
    "Structured application events, redacted before display.": "أحداث تطبيق منظمة تُنقّح قبل العرض.",
    "Evidence refreshed": "تم تحديث الأدلة",
    "Inspection-only application view. Mutation authority remains in the existing Git control plane.": "عرض فحص فقط. وتبقى صلاحية التعديل في طبقة التحكم الحالية بـGit.",
    "Repository": "المستودع",
    "Branch": "الفرع",
    "HEAD": "HEAD",
    "Worktree": "شجرة العمل",
    "Authority": "الصلاحية",
    "Git snapshot refreshed": "تم تحديث لقطة Git",
    "The UI distinguishes evidence states and never invents results.": "تميّز الواجهة بين حالات الأدلة ولا تختلق النتائج.",
    "Compile": "الترجمة",
    "Focused tests": "الاختبارات المركزة",
    "Full regression": "الاختبار الشامل",
    "Security audit": "تدقيق الأمان",
    "Provider smoke": "اختبار المزوّد",
    "Windows E2E": "اختبار Windows الشامل",
    "Reported by CI / Windows acceptance": "مُبلغ عنه بواسطة CI / قبول Windows",
    "Local credential environment required": "بيئة بيانات اعتماد محلية مطلوبة",
    "Pending current UI promotion gate": "بانتظار بوابة ترقية الواجهة الحالية",
    "Evidence is read-only on this surface": "الأدلة للقراءة فقط في هذه الواجهة",
    "The Control Center explains policy; it cannot override it.": "مركز التحكم يشرح السياسة؛ ولا يستطيع تجاوزها.",
    "Core Safety Invariants": "ثوابت أمان الـCore",
    "UNKNOWN / CONFLICT": "UNKNOWN / CONFLICT",
    "SAFE_STOP; autonomous execution is blocked": "SAFE_STOP؛ تم حظر التنفيذ الذاتي",
    "Model output": "مخرجات النموذج",
    "Untrusted input; validated before authority is granted": "مدخل غير موثوق؛ يُتحقق منه قبل منح الصلاحية",
    "Mutation": "التعديل",
    "Independent validation + authorization + checkpoint required": "مطلوب تحقق مستقل + تفويض + نقطة تحقق",
    "Git terminal": "طرفية Git",
    "Inspection-only; mutation uses the dedicated control plane": "فحص فقط؛ والتعديل يستخدم طبقة التحكم المخصصة",
    "Secrets": "الأسرار",
    "Redacted before UI activity/evidence and never rendered after import": "تُنقّح قبل نشاط/أدلة الواجهة ولا تُعرض بعد الاستيراد",
    "Non-secret application and runtime information.": "معلومات التطبيق ووقت التشغيل غير الحساسة.",
    "Environment": "البيئة",
    "Application": "التطبيق",
    "Python": "Python",
    "Platform": "المنصة",
    "Credentials rendered": "عرض بيانات الاعتماد",
    "NO": "لا",
    "Application authority": "صلاحية التطبيق",
    "typed intents over Core": "نوايا typed عبر الـCore",
    "Dashboard refreshed": "تم تحديث لوحة المعلومات",
    "Connection registry refreshed": "تم تحديث سجل الاتصالات",
    "Worker fleet refreshed": "تم تحديث أسطول العمال",
    "Settings / Diagnostics": "الإعدادات / التشخيص",
}


def _translate(text: str, language: str) -> str:
    if language == "en":
        return text
    return _TRANSLATIONS.get(text, text)


def _apply_widget_language(widget: Any, language: str) -> None:
    try:
        children = widget.winfo_children()
    except Exception:
        children = []

    for child in children:
        _apply_widget_language(child, language)

    try:
        cls = child.winfo_class() if 'child' in locals() else ""
    except Exception:
        cls = ""

    for candidate in [widget, *children]:
        try:
            current = candidate.cget("text")
        except Exception:
            continue
        if not isinstance(current, str):
            continue
        translated = _translate(current, language)
        if translated == current:
            continue
        try:
            candidate.configure(text=translated)
        except Exception:
            pass

    try:
        if widget.winfo_class() in {"Label", "TLabel", "Button", "TButton", "Entry", "TEntry", "TLabelFrame", "Labelframe"}:
            widget.configure(anchor="e", justify="right")
        elif widget.winfo_class() == "Text":
            widget.configure(justify="right")
    except Exception:
        pass


def _translate_treeview_headers(widget: Any, language: str) -> None:
    try:
        if widget.winfo_class() != "Treeview":
            return
        for column in widget["columns"]:
            heading = widget.heading(column).get("text", "")
            if isinstance(heading, str) and heading:
                widget.heading(column, text=_translate(heading, language))
    except Exception:
        return


def install_bilingual_support(app_class: Any) -> None:
    """Add English/Arabic UI switching without changing Core authority."""
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
        if hasattr(self, "language_button"):
            self.language_button.configure(
                text="English" if self.language == "ar" else "العربية"
            )
        self._apply_bilingual_language()

    def _apply_bilingual_language(self: Any) -> None:
        _apply_widget_language(self.root, self.language)
        for widget in self.root.winfo_children():
            for descendant in [widget, *widget.winfo_children()]:
                _translate_treeview_headers(descendant, self.language)
        if hasattr(self, "language_button"):
            self.language_button.configure(
                text="English" if self.language == "ar" else "العربية"
            )

    app_class.__init__ = __init__
    app_class.show = show
    app_class.toggle_language = toggle_language
    app_class._apply_bilingual_language = _apply_bilingual_language
    setattr(app_class, _INSTALLED, True)
