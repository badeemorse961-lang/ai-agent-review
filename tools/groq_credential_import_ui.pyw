from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from protected_secret_store import SecretStoreError, WindowsProtectedSecretStore
from tools.groq_known_match_import import TARGET_IDS, import_known_matches, preview_known_matches


class GroqCredentialImportApp:
    """Windows operator UI for safe Groq credential import and local readiness."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AI-Agent — Groq Credential Import")
        self.root.geometry("980x720")
        self.root.minsize(820, 620)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose the local Groq TXT source.")
        self.import_button: ttk.Button | None = None
        self.verify_button: ttk.Button | None = None
        self._selected_path: Path | None = None
        self._preview_data: dict[str, object] = {}
        self._build()

    def _build(self) -> None:
        ttk.Label(self.root, text="Groq Credential Import", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(20, 4)
        )
        ttk.Label(
            self.root,
            text=(
                "Pick the existing local TXT pool. The UI detects credentials that already belong to "
                "GROQ-01 / GROQ-02 by fingerprint, without displaying or creating new connection IDs."
            ),
            wraplength=900,
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 16))

        main = ttk.Frame(self.root, padding=24)
        main.grid(row=2, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(4, weight=1)

        ttk.Label(main, text="Groq TXT source").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(main, textvariable=self.path_var, state="readonly").grid(row=0, column=1, sticky="ew")
        ttk.Button(main, text="Choose file…", command=self._choose_file).grid(row=0, column=2, padx=(10, 0))

        ttk.Label(
            main,
            text=(
                "Supported source formats: labeled GROQ-01=… / GROQ-02=… entries, or a larger unlabeled pool. "
                "For an unlabeled pool, only fingerprints matching the existing stable IDs are eligible."
            ),
            wraplength=820,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(12, 12))

        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.import_button = ttk.Button(actions, text="Import matching credentials", command=self._import, state="disabled")
        self.import_button.pack(side="left", padx=(0, 8))
        self.verify_button = ttk.Button(actions, text="Verify readiness", command=self._verify, state="disabled")
        self.verify_button.pack(side="left")

        self.output = tk.Text(main, wrap="word", font=("Consolas", 10), relief="flat", height=22)
        self.output.grid(row=4, column=0, columnspan=3, sticky="nsew")
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
        self._selected_path = selected
        self._preview(selected)

    def _preview(self, path: Path) -> None:
        self._clear_output()
        self._preview_data = {}
        self._set_buttons(False, False)
        if path.suffix.lower() != ".txt":
            self._write("IMPORT BLOCKED\n\nSelected source must be a .txt file.\n")
            self.status_var.set("Invalid source file.")
            return
        try:
            data = preview_known_matches(path)
        except Exception as exc:
            self._write(f"IMPORT BLOCKED\n\nCould not read source: {type(exc).__name__}\n")
            self.status_var.set("Source could not be read.")
            return

        self._preview_data = data
        matched = data.get("matched_ids", [])
        labeled = data.get("labeled_target_ids", [])
        self._write("SAFE PREVIEW\n\n")
        self._write(f"Source: {path}\n")
        self._write(f"Labeled entries: {data.get('labeled_count', 0)}\n")
        self._write(f"Unlabeled entries: {data.get('unlabeled_count', 0)}\n")
        self._write(f"Known target matches: {', '.join(matched) if matched else '(none)'}\n")
        self._write(f"Explicit labeled matches: {', '.join(labeled) if labeled else '(none)'}\n")
        self._write(f"Unmatched entries: {data.get('unmatched_count', 0)}\n\n")

        if set(matched) == set(TARGET_IDS):
            self._write("READY TO IMPORT MATCHING GROQ CREDENTIALS\n")
            self._write("Stable IDs preserved: GROQ-01, GROQ-02\n")
            self._write("Unknown credentials will be ignored; no new IDs are created.\n")
            self.status_var.set("Both stable Groq IDs were found by safe fingerprint matching.")
            self._set_buttons(True, False)
        elif matched:
            self._write("PARTIAL MATCH\n")
            self._write("Only matched stable IDs can be imported. No new IDs will be created.\n")
            self.status_var.set("Only some stable Groq IDs were found.")
            self._set_buttons(True, False)
        else:
            self._write("IMPORT BLOCKED\n")
            self._write("No credential in this source matches the existing GROQ-01 / GROQ-02 fingerprints.\n")
            self.status_var.set("No known stable Groq credential was found.")

    def _import(self) -> None:
        path = self._selected_path
        if path is None:
            self.status_var.set("Choose a source file first.")
            return
        try:
            summary = import_known_matches(path)
            self._clear_output()
            self._write("IMPORT COMPLETE\n\n")
            self._write(f"Imported stable IDs: {', '.join(summary.get('imported_ids', [])) or '(none)'}\n")
            self._write(f"Already protected: {', '.join(summary.get('already_present_ids', [])) or '(none)'}\n")
            self._write(f"Unknown/unmatched source entries ignored: {summary.get('unmatched_count', 0)}\n")
            self._write(f"Rejected labeled entries: {summary.get('rejected_count', 0)}\n")
            self._write("Stable IDs created: NONE\n")
            self._write("Raw credentials displayed: NO\n")
            self._write("Storage: WindowsProtectedSecretStore\n\n")
            self._write("Next step: click Verify readiness.\n")
            self.status_var.set("Matching credentials imported into protected storage.")
            self._set_buttons(False, True)
        except Exception as exc:
            self.status_var.set("Import failed; no readiness claim made.")
            self._set_buttons(False, False)
            messagebox.showerror("Groq import failed", f"{type(exc).__name__}: {exc}")

    def _verify(self) -> None:
        try:
            store = WindowsProtectedSecretStore()
            lines: list[str] = []
            all_ready = True
            for connection_id in TARGET_IDS:
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
            self._write("No provider inference or routing activation was performed.\n")
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


def main() -> None:
    try:
        GroqCredentialImportApp().run()
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("AI-Agent Groq Import", f"Startup failed: {type(exc).__name__}: {exc}")
            root.destroy()
        except Exception:
            raise


if __name__ == "__main__":
    main()
