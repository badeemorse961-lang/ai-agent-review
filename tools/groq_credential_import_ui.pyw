from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection_manager import PROVIDER_PREFIXES, import_provider, load_registry, read_secret_source
from protected_secret_store import SecretStoreError, WindowsProtectedSecretStore

TARGET_IDS = ("GROQ-01", "GROQ-02")


class GroqCredentialImportApp:
    """Windows-only operator UI for the official Groq credential import path."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AI-Agent — Groq Credential Import")
        self.root.geometry("900x650")
        self.root.minsize(760, 560)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select the local Groq TXT source to begin.")
        self.import_button: ttk.Button | None = None
        self.verify_button: ttk.Button | None = None
        self._build()

    def _build(self) -> None:
        ttk.Label(self.root, text="Groq Credential Import", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(20, 4)
        )
        ttk.Label(
            self.root,
            text=("Choose the existing local Groq TXT source. The preview exposes connection IDs only; "
                  "the credential values never appear in the window."),
            wraplength=820,
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 16))

        main = ttk.Frame(self.root, padding=24)
        main.grid(row=2, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(3, weight=1)

        ttk.Label(main, text="Groq TXT source").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(main, textvariable=self.path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(main, text="Choose file…", command=self._choose_file).grid(row=0, column=2, padx=(10, 0))

        ttk.Label(
            main,
            text=("Expected stable IDs: GROQ-01 and GROQ-02. "
                  "The import button stays disabled unless both are explicitly labeled and no extra IDs exist."),
            wraplength=760,\        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(12, 12))

        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.import_button = ttk.Button(actions, text="Import & Protect", command=self._import, state="disabled")
        self.import_button.pack(side="left", padx=(0, 8))
        self.verify_button = ttk.Button(actions, text="Verify readiness", command=self._verify, state="disabled")
        self.verify_button.pack(side="left")

        self.output = tk.Text(main, wrap="word", font=("Consolas", 10), relief="flat", height=20)
        self.output.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.output.configure(state="disabled")

        ttk.Label(self.root, textvariable=self.status_var).grid(row=3, column=0, sticky="ew", padx=24, pady=(8, 18))

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose Groq credential TXT",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        selected = Path(path).resolve()
        self.path_var.set(str(selected))
        self._preview(selected)

    def _preview(self, path: Path) -> None:
        self._clear_output()
        if path.suffix.lower() != ".txt":
            self._write("IMPORT BLOCKED\n\nSelected source must be a .txt file.\n")
            self.status_var.set("Invalid source file.")
            self._set_buttons(False, False)
            return
        try:
            labeled, unlabeled = read_secret_source(path, PROVIDER_PREFIXES["groq"])
        except Exception as exc:
            self._write(f"IMPORT BLOCKED\n\nCould not read source: {type(exc).__name__}\n")
            self.status_var.set("Source could not be read.")
            self._set_buttons(False, False)
            return

        found = sorted(labeled)
        missing = [item for item in TARGET_IDS if item not in labeled]
        unexpected = [item for item in found if item not in TARGET_IDS]
        self._write("SAFE PREVIEW\n\n")
        self._write(f"Source: {path}\n")
        self._write(f"Labeled IDs: {', '.join(found) if found else '(none)'}\n")
        self._write(f"Unlabeled entries: {len(unlabeled)}\n")
        self._write(f"Missing required IDs: {', '.join(missing) if missing else '(none)'}\n")
        self._write(f"Unexpected IDs: {', '.join(unexpected) if unexpected else '(none)'}\n\n")

        exact = not unlabeled and not missing and not unexpected and set(labeled) == set(TARGET_IDS)
        if exact:
            self._write("READY FOR OFFICIAL IMPORT\n")
            self._write("Stable identity preserved: GROQ-01, GROQ-02\n")
            self._write("No new connection IDs will be created by this flow.\n")
            self.status_var.set("Source is valid.")
            self._set_buttons(True, False)
        else:
            self._write("IMPORT BLOCKED\n")
            self._write("Use exactly GROQ-01 and GROQ-02 as labeled entries.\n")
            self.status_var.set("Fix the local TXT source and select it again.")
            self._set_buttons(False, False)

    def _import(self) -> None:
        path = Path(self.path_var.get().strip()).resolve()
        try:
            labeled, unlabeled = read_secret_source(path, "GROQ")
            if unlabeled or set(labeled) != set(TARGET_IDS):
                raise ValueError("Import source must contain exactly labeled GROQ-01 and GROQ-02 entries")

            before_ids = set(load_registry().get("connections", {}).keys())
            registry = load_registry()
            summary = import_provider("groq", path, registry, "GROQ")
            after_ids = set(registry.get("connections", {}).keys())
            unexpected_created = after_ids - before_ids - set(TARGET_IDS)
            if unexpected_created:
                raise RuntimeError("Unexpected connection ID creation detected; import result rejected")

            self._clear_output()
            self._write("IMPORT COMPLETE\n\n")
            self._write(f"Provider: {summary.provider}\n")
            self._write(f"Imported records: {summary.imported_count}\n")
            self._write(f"Already present: {summary.already_present_count}\n")
            self._write(f"Rejected: {summary.rejected_count}\n")
            self._write(f"Stable IDs touched: {', '.join(summary.connection_ids) if summary.connection_ids else '(none)'}\n")
            self._write("Raw credentials displayed: NO\n")
            self._write("Storage: WindowsProtectedSecretStore\n")
            self.status_var.set("Import completed through the official path.")
            self._set_buttons(False, True)
        except Exception as exc:
            self.status_var.set("Import failed; no readiness claim made.")
            self._set_buttons(False, False)
            messagebox.showerror("Groq import failed", f"{type(exc).__name__}: {exc}")

    def _verify(self) -> None:
        try:
            registry = load_registry().get("connections", {})
            store = WindowsProtectedSecretStore()
            lines: list[str] = []
            all_ready = True
            for connection_id in TARGET_IDS:
                item = registry.get(connection_id)
                if not isinstance(item, dict) or item.get("provider") != "groq":
                    lines.append(f"{connection_id} = NOT_READY — CONNECTION_ID_MISMATCH")
                    all_ready = False
                    continue
                try:
                    secret = store.get(connection_id, "groq")
                except SecretStoreError:
                    lines.append(f"{connection_id} = NOT_READY — SECRET_RECORD_MISSING")
                    all_ready = False
                    continue
                if isinstance(secret, str) and secret:
                    lines.append(f"{connection_id} = READY")
                else:
                    lines.append(f"{connection_id} = NOT_READY — UNRESOLVED")
                    all_ready = False

            self._clear_output()
            self._write("READINESS VERIFICATION\n\n")
            self._write("\n".join(lines))
            self._write("\n\nCredential values displayed: NO\n")
            self.status_var.set("Groq readiness verified." if all_ready else "Readiness verification found a failure.")
        except OSError:
            self._clear_output()
            self._write("READINESS VERIFICATION\n\nSTORE_ACCESS_FAILURE\n")
            self.status_var.set("Protected store access failed.")
        except Exception as exc:
            self._clear_output()
            self._write(f"READINESS VERIFICATION\n\nUNRESOLVED — {type(exc).__name__}\n")
            self.status_var.set("Readiness verification is unresolved.")

    def _set_buttons(self, can_import: bool, can_verify: bool) -> None:
        if self.import_button is not None:
            self.import_button.configure(state="normal" if can_import else "disabled")
        if self.verify_button is not None:
            self.verify_button.configure(state="normal" if can_verify else "disabled")

    def _write(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _clear_output(self) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    GroqCredentialImportApp().run()
