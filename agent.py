import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


# ============================================================
# إعدادات النظام
# ============================================================

ROOT = Path(r"D:\AI-Agent\Sandbox\agent-test").resolve()

LOCAL_MODEL = "qwen2.5-coder:3b"
GROQ_MODEL = "openai/gpt-oss-120b"

OLLAMA_URL = "http://localhost:11434/api/generate"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

ALLOWED_FILES = {
    "calculator.py",
    "test_calculator.py",
}

BACKUP_DIR = ROOT / ".agent_backups"


# ============================================================
# أدوات الملفات
# ============================================================

def read_file(filename):
    if filename not in ALLOWED_FILES:
        raise RuntimeError("الملف غير مسموح: " + filename)

    path = (ROOT / filename).resolve()

    if path.parent != ROOT:
        raise RuntimeError("محاولة الخروج من مجلد المشروع")

    if not path.exists():
        raise RuntimeError("الملف غير موجود: " + filename)

    return path.read_text(encoding="utf-8")


def create_backup():
    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / timestamp
    backup.mkdir()

    for filename in ALLOWED_FILES:
        source = ROOT / filename

        if source.exists():
            shutil.copy2(source, backup / filename)

    print("تم إنشاء نسخة احتياطية:", backup)
    return backup


def restore_backup(backup):
    print("جارٍ استرجاع الحالة السابقة...")

    for filename in ALLOWED_FILES:
        source = backup / filename
        target = ROOT / filename

        if source.exists():
            shutil.copy2(source, target)

    print("تم الاسترجاع بنجاح.")


# ============================================================
# الاتصال بـ Qwen المحلي
# ============================================================

def ask_qwen(prompt):
    payload = {
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False
    }

    data = json.dumps(payload).encode("utf-8")

    request = Request(
        OLLAMA_URL,
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urlopen(request, timeout=600) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    return result["response"]


# ============================================================
# الاتصال بـ Groq
# ============================================================

def ask_groq(prompt):
    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY غير موجود في نافذة PowerShell الحالية."
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.1,
        "reasoning_effort": "high"
    }

    data = json.dumps(payload).encode("utf-8")

    request = Request(
        GROQ_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key
        },
        method="POST"
    )

    with urlopen(request, timeout=600) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    return result["choices"][0]["message"]["content"]


# ============================================================
# تشغيل الاختبارات
# ============================================================

def run_tests():
    result = subprocess.run(
        ["python", "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True
    )

    return {
        "code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr
    }


# ============================================================
# قراءة JSON من رد النموذج
# ============================================================

def parse_json(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "النموذج لم يرجع JSON صحيح.\n\n" + text
        ) from exc


# ============================================================
# التحقق من التعديلات
# ============================================================

def validate_edits(edits):
    if not isinstance(edits, list):
        raise RuntimeError("قائمة التعديلات غير صحيحة.")

    for edit in edits:
        if not isinstance(edit, dict):
            raise RuntimeError("صيغة أحد التعديلات غير صحيحة.")

        filename = edit.get("file")
        old = edit.get("old")
        new = edit.get("new")

        if filename not in ALLOWED_FILES:
            raise RuntimeError(
                "النموذج حاول تعديل ملف غير مسموح: " + str(filename)
            )

        if not isinstance(old, str) or not isinstance(new, str):
            raise RuntimeError("old/new يجب أن يكونا نصين.")

        if old == new:
            raise RuntimeError(
                "التعديل المقترح لا يغير شيئًا في " + filename
            )

        current = read_file(filename)

        if old not in current:
            raise RuntimeError(
                "النص المطلوب تعديله غير موجود حرفيًا في " + filename
            )


def apply_edits(edits):
    validate_edits(edits)

    for edit in edits:
        filename = edit["file"]
        old = edit["old"]
        new = edit["new"]

        path = ROOT / filename
        current = path.read_text(encoding="utf-8")

        updated = current.replace(old, new, 1)

        path.write_text(
            updated,
            encoding="utf-8"
        )

        print("تم تعديل:", filename)


# ============================================================
# تجهيز محتوى الملفات للنموذج
# ============================================================

def build_files_text():
    result = {}

    for filename in ALLOWED_FILES:
        path = ROOT / filename

        if path.exists():
            result[filename] = read_file(filename)

    return result


def files_to_text(files_data):
    parts = []

    for filename, content in files_data.items():
        parts.append(
            "===== " + filename + " =====\n" + content
        )

    return "\n\n".join(parts)


# ============================================================
# Prompt Qwen
# ============================================================

def build_qwen_prompt(task, files_data):
    content = files_to_text(files_data)

    parts = [
        "أنت مساعد برمجي محلي داخل نظام تطوير آمن.",
        "",
        "المهمة:",
        task,
        "",
        "الملفات الحالية:",
        content,
        "",
        "القواعد:",
        "1. لا تخترع متطلبات.",
        "2. لا تعيد كتابة المشروع.",
        "3. اقترح أقل تعديل آمن.",
        "4. لا تعدل ملفات غير ضرورية.",
        "5. إذا لم تجد تعديلًا واضحًا أعد edits كقائمة فارغة.",
        "6. لا تدعي أنك شغلت الاختبارات.",
        "",
        "أرجع JSON فقط بهذا الشكل:",
        "{",
        '  "confidence": 0.0,',
        '  "analysis": "شرح مختصر",',
        '  "edits": [',
        "    {",
        '      "file": "calculator.py",',
        '      "old": "النص القديم حرفيًا",',
        '      "new": "النص الجديد"',
        "    }",
        "  ]",
        "}"
    ]

    return "\n".join(parts)


# ============================================================
# Prompt GPT-OSS
# ============================================================

def build_groq_prompt(task, files_data, previous_analysis, test_result=None):
    content = files_to_text(files_data)

    parts = [
        "أنت مهندس برمجيات خبير داخل وكيل تطوير آمن.",
        "",
        "المهمة:",
        task,
        "",
        "الملفات الحالية:",
        content,
        "",
        "تحليل النموذج السابق:",
        previous_analysis,
        ""
    ]

    if test_result is not None:
        parts.extend([
            "نتيجة الاختبار الحقيقي:",
            "رمز الخروج: " + str(test_result["code"]),
            "",
            "المخرجات:",
            test_result["stdout"],
            "",
            "الأخطاء:",
            test_result["stderr"],
            ""
        ])

    parts.extend([
        "القواعد:",
        "1. اكتشف المشكلة الحقيقية فقط.",
        "2. لا تخترع متطلبات.",
        "3. لا تعيد كتابة المشروع.",
        "4. اقترح أقل تعديل آمن.",
        "5. لا تعدل ملفات غير ضرورية.",
        "6. إذا لم تجد إصلاحًا واضحًا وآمنًا فلا تقترح تعديلًا.",
        "7. لا تدعي أنك شغلت الاختبارات.",
        "",
        "أرجع JSON فقط بهذا الشكل:",
        "{",
        '  "confidence": 0.0,',
        '  "analysis": "تحليل هندسي",',
        '  "edits": [',
        "    {",
        '      "file": "calculator.py",',
        '      "old": "النص القديم حرفيًا",',
        '      "new": "النص الجديد"',
        "    }",
        "  ]",
        "}"
    ])

    return "\n".join(parts)


# ============================================================
# البرنامج الرئيسي
# ============================================================

def main():
    print("=" * 60)
    print("        مدير العقول - النسخة التجريبية")
    print("=" * 60)

    task_path = ROOT / "TASK.md"

    if not task_path.exists():
        raise RuntimeError("ملف TASK.md غير موجود.")

    task = task_path.read_text(
        encoding="utf-8"
    )

    files_data = build_files_text()

    print("\n[1] قراءة المهمة والملفات...")

    # --------------------------------------------------------
    # محاولة Qwen المحلية
    # --------------------------------------------------------

    qwen_prompt = build_qwen_prompt(
        task,
        files_data
    )

    print("[2] إرسال المهمة إلى Qwen المحلي...")

    qwen_raw = ask_qwen(qwen_prompt)

    print("\n--- رد Qwen ---")
    print(qwen_raw)
    print("----------------")

    qwen = parse_json(qwen_raw)

    qwen_confidence = float(
        qwen.get("confidence", 0)
    )

    qwen_edits = qwen.get("edits", [])

    # --------------------------------------------------------
    # نتحقق من المشروع بالاختبارات قبل الوثوق بـQwen
    # --------------------------------------------------------

    print("\n[3] تشغيل الاختبارات الحالية...")

    baseline = run_tests()

    if baseline["stdout"]:
        print(baseline["stdout"])

    if baseline["stderr"]:
        print(baseline["stderr"])

    # المشروع سليم بالفعل
    if baseline["code"] == 0 and not qwen_edits:
        print("\nالاختبارات ناجحة، ولا يوجد تعديل مقترح.")
        print("انتهت المهمة بأمان ✅")
        return

    # Qwen لم يجد تعديلًا لكن الاختبارات فاشلة
    if baseline["code"] != 0 and not qwen_edits:
        print("\nQwen لم يقترح تعديلًا رغم فشل الاختبارات.")
        print("سيتم التصعيد إلى GPT-OSS 120B.")

        groq_prompt = build_groq_prompt(
            task,
            files_data,
            qwen.get("analysis", ""),
            baseline
        )

        print("\n[4] إرسال المهمة إلى GPT-OSS 120B...")

        groq_raw = ask_groq(groq_prompt)

        print("\n--- رد GPT-OSS ---")
        print(groq_raw)
        print("------------------")

        decision = parse_json(groq_raw)

        if float(decision.get("confidence", 0)) < 0.70:
            print("\n[إيقاف آمن]")
            print("الثقة في الإصلاح منخفضة.")
            return

        edits = decision.get("edits", [])

    # Qwen لديه تعديل لكن الثقة منخفضة
    elif qwen_confidence < 0.70:
        print("\nQwen غير واثق بما يكفي.")
        print("سيتم التصعيد إلى GPT-OSS 120B.")

        groq_prompt = build_groq_prompt(
            task,
            files_data,
            qwen.get("analysis", ""),
            baseline if baseline["code"] != 0 else None
        )

        print("\n[4] إرسال المهمة إلى GPT-OSS 120B...")

        groq_raw = ask_groq(groq_prompt)

        print("\n--- رد GPT-OSS ---")
        print(groq_raw)
        print("------------------")

        decision = parse_json(groq_raw)

        if float(decision.get("confidence", 0)) < 0.70:
            print("\n[إيقاف آمن]")
            print("الثقة في الإصلاح منخفضة.")
            return

        edits = decision.get("edits", [])

    else:
        decision = qwen
        edits = qwen_edits

    # --------------------------------------------------------
    # لا يوجد تعديل
    # --------------------------------------------------------

    if not edits:
        print("\n[إيقاف آمن]")
        print("لم يتم العثور على تعديل آمن.")
        return

    # --------------------------------------------------------
    # نقطة رجوع
    # --------------------------------------------------------

    print("\n[5] إنشاء نسخة احتياطية...")
    backup = create_backup()

    # --------------------------------------------------------
    # تطبيق التعديل
    # --------------------------------------------------------

    try:
        print("\n[6] التحقق من التعديل وتطبيقه...")
        apply_edits(edits)

    except Exception as exc:
        print("\nتم رفض التعديل ❌")
        print(str(exc))
        restore_backup(backup)
        return

    # --------------------------------------------------------
    # اختبار بعد التعديل
    # --------------------------------------------------------

    print("\n[7] تشغيل الاختبارات بعد التعديل...")

    result = run_tests()

    if result["stdout"]:
        print(result["stdout"])

    if result["stderr"]:
        print(result["stderr"])

    if result["code"] == 0:
        print("\n" + "=" * 60)
        print("نجح الإصلاح ✅")
        print("=" * 60)
        return

    # --------------------------------------------------------
    # التعديل فشل
    # --------------------------------------------------------

    print("\n[8] التعديل لم ينجح.")
    print("سيتم التراجع قبل أي محاولة جديدة.")

    restore_backup(backup)

    current_files = build_files_text()

    repair_prompt = build_groq_prompt(
        task,
        current_files,
        "المحاولة السابقة فشلت في الاختبارات.",
        result
    )

    print("\n[9] إرسال الفشل الحقيقي إلى GPT-OSS 120B...")

    repair_raw = ask_groq(repair_prompt)

    print("\n--- اقتراح الإصلاح ---")
    print(repair_raw)
    print("-----------------------")

    repair = parse_json(repair_raw)

    if float(repair.get("confidence", 0)) < 0.70:
        print("\n[إيقاف آمن]")
        print("الإصلاح غير موثوق.")
        return

    repair_edits = repair.get("edits", [])

    if not repair_edits:
        print("\n[إيقاف آمن]")
        print("لا يوجد إصلاح واضح.")
        return

    # --------------------------------------------------------
    # تطبيق الإصلاح الثاني
    # --------------------------------------------------------

    backup2 = create_backup()

    try:
        print("\n[10] تطبيق الإصلاح...")
        apply_edits(repair_edits)

    except Exception as exc:
        print("\nتم رفض الإصلاح ❌")
        print(str(exc))
        restore_backup(backup2)
        return

    # --------------------------------------------------------
    # الاختبار النهائي
    # --------------------------------------------------------

    print("\n[11] إعادة الاختبار...")

    final_result = run_tests()

    if final_result["stdout"]:
        print(final_result["stdout"])

    if final_result["stderr"]:
        print(final_result["stderr"])

    if final_result["code"] == 0:
        print("\n" + "=" * 60)
        print("نجح الإصلاح الذاتي ✅")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("فشل الإصلاح الذاتي ❌")
        print("سيتم استرجاع الحالة الآمنة.")
        print("=" * 60)

        restore_backup(backup2)


if __name__ == "__main__":
    main()