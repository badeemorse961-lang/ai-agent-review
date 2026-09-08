from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TRANSLATIONS: Mapping[str, str] = {
    "AI-Agent": "الوكيل الذكي", "Control Center": "مركز التحكم", "Dashboard": "لوحة المعلومات", "Chat": "الدردشة", "Projects": "المشاريع", "Connections & Pools": "الاتصالات والمجموعات", "Workers": "العمال", "Run / Plan": "التنفيذ / الخطة", "Evidence & Activity": "الأدلة والنشاط", "Git & Changes": "Git والتغييرات", "Tests & Verification": "الاختبارات والتحقق", "Safety & Policy": "الأمان والسياسات", "Settings / Diagnostics": "الإعدادات / التشخيص", "Toggle theme": "تبديل المظهر", "Exit": "خروج", "English": "الإنجليزية", "Arabic": "العربية", "Overview": "نظرة عامة", "Leader": "القائد", "Workspace": "مساحة العمل", "Connections": "الاتصالات", "Fleet": "الأسطول", "Run": "التنفيذ", "Evidence": "الأدلة", "Tests": "الاختبارات", "Safety": "الأمان", "Settings": "الإعدادات", "Operational state derived from the Core; no simulated runtime data.": "الحالة التشغيلية مستمدة من الـCore؛ لا توجد بيانات تشغيلية وهمية.", "Chat with Central Leader": "الدردشة مع القائد المركزي", "Natural-language goals become typed application intents; they are never shell commands.": "الأهداف بلغة طبيعية تتحول إلى نوايا تطبيق typed؛ ولا تصبح أوامر shell أبدًا.", "New Goal": "هدف جديد", "Goal": "الهدف", "Task ID": "معرّف المهمة", "Send Goal": "إرسال الهدف", "Leader Response": "استجابة القائد", "Goal accepted": "تم قبول الهدف", "Tasks": "المهام", "Select a bounded workspace; the Core remains responsible for project classification.": "اختر مساحة عمل محددة؛ ويظل الـCore مسؤولًا عن تصنيف المشروع.", "Active Workspace": "مساحة العمل النشطة", "Workspace path": "مسار مساحة العمل", "Select": "اختيار", "Project State": "حالة المشروع", "Project state, detected documentation, health, conflicts, and gaps are read from the Core project-understanding pipeline.": "تُقرأ حالة المشروع والوثائق المكتشفة والصحة والتعارضات والفجوات من مسار فهم المشروع في الـCore.", "Registry assignments are authoritative; runtime health is observational.": "تعيينات السجل هي المرجع الموثوق؛ وصحة التشغيل للمراقبة فقط.", "Refresh": "تحديث", "Connection ID": "معرّف الاتصال", "Provider": "المزوّد", "Model": "النموذج", "Assignment": "التعيين", "Runtime": "وقت التشغيل", "Metadata": "البيانات الوصفية", "Fingerprint": "البصمة", "Import openrouter source": "استيراد مصدر OpenRouter", "Import groq source": "استيراد مصدر Groq", "Workers / Fleet": "العمال / الأسطول", "Router-owned health, leases, and availability; the UI adds no worker authority.": "الصحة والتأجير والتوافر مملوكة للموجّه؛ ولا تضيف الواجهة أي صلاحية للعمال.", "Healthy": "سليم", "Failed": "فاشل", "Leased": "مؤجّر", "Active Leases": "عقود التأجير النشطة", "Worker": "العامل", "Role": "الدور", "Standby": "احتياطي", "Execution remains exclusively owned by the canonical Core runtime.": "يبقى التنفيذ مملوكًا حصريًا لوقت تشغيل الـCore المعياري.", "Canonical Run": "التنفيذ المعياري", "Run Task": "تنفيذ المهمة", "Run Evidence": "أدلة التنفيذ", "Structured application events, redacted before display.": "أحداث تطبيق منظمة تُنقّح قبل العرض.", "Repository": "المستودع", "Branch": "الفرع", "Worktree": "شجرة العمل", "Authority": "الصلاحية", "The UI distinguishes evidence states and never invents results.": "تميّز الواجهة بين حالات الأدلة ولا تختلق النتائج.", "Compile": "الترجمة", "Focused tests": "الاختبارات المركزة", "Full regression": "الاختبار الشامل", "Security audit": "تدقيق الأمان", "Provider smoke": "اختبار المزوّد", "Windows E2E": "اختبار Windows الشامل", "Reported by CI / Windows acceptance": "مُبلغ عنه بواسطة CI / قبول Windows", "Local credential environment required": "بيئة بيانات اعتماد محلية مطلوبة", "Pending current UI promotion gate": "بانتظار بوابة ترقية الواجهة الحالية", "Evidence is read-only on this surface": "الأدلة للقراءة فقط في هذه الواجهة", "The Control Center explains policy; it cannot override it.": "مركز التحكم يشرح السياسة؛ ولا يستطيع تجاوزها.", "Core Safety Invariants": "ثوابت أمان الـCore", "UNKNOWN / CONFLICT": "UNKNOWN / CONFLICT", "SAFE_STOP; autonomous execution is blocked": "SAFE_STOP؛ تم حظر التنفيذ الذاتي", "Model output": "مخرجات النموذج", "Untrusted input; validated before authority is granted": "مدخل غير موثوق؛ يُتحقق منه قبل منح الصلاحية", "Mutation": "التعديل", "Independent validation + authorization + checkpoint required": "مطلوب تحقق مستقل + تفويض + نقطة تحقق", "Git terminal": "طرفية Git", "Inspection-only; mutation uses the dedicated control plane": "فحص فقط؛ والتعديل يستخدم طبقة التحكم المخصصة", "Secrets": "الأسرار", "Redacted before UI activity/evidence and never rendered after import": "تُنقّح قبل نشاط/أدلة الواجهة ولا تُعرض بعد الاستيراد", "Current Safety Evidence": "دليل الأمان الحالي", "Reason": "السبب", "Affected task/run": "المهمة/التنفيذ المتأثر", "Recovery": "الاسترداد", "Non-secret application and runtime information.": "معلومات التطبيق ووقت التشغيل غير الحساسة.", "Environment": "البيئة", "Application": "التطبيق", "Platform": "المنصة", "Credentials rendered": "عرض بيانات الاعتماد", "Application authority": "صلاحية التطبيق", "typed intents over Core": "نوايا typed عبر الـCore", "NO": "لا", "YES": "نعم", "Dashboard refreshed": "تم تحديث لوحة المعلومات", "Connection registry refreshed": "تم تحديث سجل الاتصالات", "Worker fleet refreshed": "تم تحديث أسطول العمال", "Safety evidence refreshed": "تم تحديث دليل الأمان",
}

def _all_widgets(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _all_widgets(child)


def _translate_text(text: str, language: str) -> str:
    if language == "en":
        return text
    stripped = text.strip()
    translated = TRANSLATIONS.get(stripped, stripped)
    if translated == stripped:
        return text
    prefix = text[: len(text) - len(text.lstrip())]
    suffix = text[len(text.rstrip()):]
    return f"{prefix}{translated}{suffix}"


def _apply(widget: Any, language: str) -> None:
    for item in _all_widgets(widget):
        try:
            if not hasattr(item, "_cc_original_text"):
                current = item.cget("text")
                if isinstance(current, str):
                    setattr(item, "_cc_original_text", current)
        except Exception:
            pass
        try:
            original = getattr(item, "_cc_original_text", None)
            if isinstance(original, str) and original:
                item.configure(text=_translate_text(original, language))
        except Exception:
            pass
        try:
            if item.winfo_class() == "Treeview":
                for column in item["columns"]:
                    original = getattr(item, f"_cc_heading_{column}", None)
                    if original is None:
                        original = item.heading(column).get("text", "")
                        setattr(item, f"_cc_heading_{column}", original)
                    if isinstance(original, str):
                        item.heading(column, text=_translate_text(original, language))
        except Exception:
            pass
        try:
            cls = item.winfo_class()
            if language == "ar":
                if cls in {"Label", "TLabel", "Button", "TButton", "Entry", "TEntry", "TLabelFrame", "Labelframe"}:
                    item.configure(anchor="e", justify="right")
                elif cls == "Text":
                    item.configure(justify="right")
            elif cls == "Text":
                item.configure(justify="left")
            elif cls in {"Label", "TLabel", "Button", "TButton", "Entry", "TEntry", "TLabelFrame", "Labelframe"}:
                item.configure(anchor="w", justify="left")
        except Exception:
            pass


def install_bilingual_support(app_class: Any) -> None:
    if getattr(app_class, "_bilingual_runtime_installed", False):
        return
    original_init = app_class.__init__
    original_show = app_class.show

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.language = "en"
        sidebar = self.root.grid_slaves(row=0, column=0)[0]
        self.language_button = self.ttk.Button(sidebar, text="العربية", command=self.toggle_language)
        self.language_button.pack(fill="x", pady=(2, 2), before=self.theme_button)
        self.language_button.lift()
        self.root.update_idletasks()

    def show(self: Any, page: str) -> None:
        original_show(self, page)
        _apply(self.root, getattr(self, "language", "en"))
        if hasattr(self, "language_button"):
            self.language_button.configure(text="English" if self.language == "ar" else "العربية")

    def toggle_language(self: Any) -> None:
        self.language = "ar" if getattr(self, "language", "en") == "en" else "en"
        _apply(self.root, self.language)
        self.language_button.configure(text="English" if self.language == "ar" else "العربية")

    app_class.__init__ = __init__
    app_class.show = show
    app_class.toggle_language = toggle_language
    setattr(app_class, "_bilingual_runtime_installed", True)
