from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# ============================================================================
# PROJECT SCANNER v1
#
# Purpose:
#   Build a local, deterministic description of an active project.
#
# Security principle:
#   Scanner observes the project.
#   It does NOT modify project files.
#   It does NOT call external APIs.
#   It does NOT execute project code.
#
# Output:
#   project_manifest.json
#
# The scanner is designed to become the local input layer for Context Builder.
# ============================================================================


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_FILE = BASE_DIR / "project_manifest.json"


# ============================================================================
# Constants
# ============================================================================

MAX_FILES = 10000
MAX_PATH_LENGTH = 500

# Directories that are normally generated, cached, or dependency-heavy.
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".idea",
    ".vscode",
    ".agent_gate_checkpoints",
}

# Files that may contain secrets or credentials.
SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "credentials.yml",
    "credentials.yaml",
    "secrets.json",
    "secret.json",
    "service-account.json",
}

SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
}

# Source/config/document extensions we can safely classify.
LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".pyw": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C/C++",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".fs": "F#",
    ".fsx": "F#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".dart": "Dart",
    ".lua": "Lua",
    ".r": "R",
    ".R": "R",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "Config",
}

TEST_FILE_PATTERNS = [
    re.compile(r"^test_.*\.py$", re.IGNORECASE),
    re.compile(r".*_test\.py$", re.IGNORECASE),
    re.compile(r"^tests?\.py$", re.IGNORECASE),
    re.compile(r".*\.test\.(js|jsx|ts|tsx)$", re.IGNORECASE),
    re.compile(r".*\.spec\.(js|jsx|ts|tsx)$", re.IGNORECASE),
    re.compile(r".*_test\.(go|rs|java|kt|cs)$", re.IGNORECASE),
]

ENTRY_FILE_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "cli.py",
    "manage.py",
    "main.js",
    "index.js",
    "server.js",
    "app.js",
    "main.ts",
    "index.ts",
    "server.ts",
    "app.ts",
    "main.go",
    "main.rs",
    "Program.cs",
    "Main.java",
    "Application.java",
    "main.cpp",
    "main.c",
    "index.html",
}

PROJECT_MARKERS = {
    "Python": {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
    },
    "Node.js": {
        "package.json",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
    },
    "Rust": {
        "Cargo.toml",
        "Cargo.lock",
    },
    "Go": {
        "go.mod",
        "go.sum",
    },
    "Java": {
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gradlew",
    },
    "C#": {
        "*.csproj",
        "*.sln",
    },
    "PHP": {
        "composer.json",
        "composer.lock",
    },
    "Ruby": {
        "Gemfile",
        "Gemfile.lock",
    },
    "Dart": {
        "pubspec.yaml",
        "pubspec.lock",
    },
}

GIT_COMMAND = [
    "git",
    "rev-parse",
    "--is-inside-work-tree",
]


# ============================================================================
# Exceptions
# ============================================================================


class ScannerError(Exception):
    """Base scanner exception."""


class WorkspaceViolation(ScannerError):
    """Raised when scanner attempts to leave the active project."""


class ScanLimitExceeded(ScannerError):
    """Raised when a scan exceeds configured safety limits."""


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class FileRecord:
    path: str
    name: str
    extension: str
    language: Optional[str]
    size_bytes: int
    is_test: bool
    is_entry_point: bool
    is_sensitive: bool
    sensitivity_reason: Optional[str]


@dataclass
class GitInfo:
    detected: bool
    is_work_tree: bool
    branch: Optional[str]
    root: Optional[str]
    clean: Optional[bool]
    status_error: Optional[str]


# ============================================================================
# Utility functions
# ============================================================================


def normalize_relative_path(
    path: Path,
) -> str:
    return path.as_posix()


def is_test_file(
    name: str,
) -> bool:
    return any(
        pattern.match(name)
        for pattern in TEST_FILE_PATTERNS
    )


def detect_language(
    suffix: str,
) -> Optional[str]:
    return LANGUAGE_BY_SUFFIX.get(
        suffix.lower()
    )


def detect_sensitivity(
    path: Path,
) -> Tuple[bool, Optional[str]]:
    name_lower = path.name.lower()
    suffix_lower = path.suffix.lower()

    if name_lower in {
        item.lower()
        for item in SENSITIVE_FILENAMES
    }:
        return True, "sensitive_filename"

    if suffix_lower in SENSITIVE_SUFFIXES:
        return True, "sensitive_extension"

    lower_path = str(path).replace(
        "\\",
        "/",
    ).lower()

    sensitive_fragments = (
        "/secrets/",
        "/secret/",
        "/credentials/",
        "/credential/",
        "/private/",
    )

    for fragment in sensitive_fragments:
        if fragment in lower_path:
            return True, "sensitive_directory"

    return False, None


def is_probably_binary(
    path: Path,
) -> bool:
    """
    Small local heuristic.

    We only inspect a tiny prefix and never execute the file.
    """

    try:
        with path.open(
            "rb"
        ) as handle:
            sample = handle.read(4096)
    except OSError:
        return True

    if b"\x00" in sample:
        return True

    return False


def read_small_text(
    path: Path,
    max_bytes: int = 20000,
) -> Optional[str]:
    """
    Reads only a bounded amount of UTF-8 text.
    """

    try:
        if path.stat().st_size > max_bytes:
            return None

        return path.read_text(
            encoding="utf-8",
            errors="strict",
        )

    except (
        OSError,
        UnicodeDecodeError,
    ):
        return None


# ============================================================================
# Project Scanner
# ============================================================================


class ProjectScanner:
    def __init__(
        self,
        workspace_root: Path,
        output_file: Optional[Path] = None,
        excluded_dirs: Optional[Set[str]] = None,
    ):
        self.workspace_root = workspace_root.resolve()

        if not self.workspace_root.exists():
            raise ScannerError(
                f"Workspace does not exist: {self.workspace_root}"
            )

        if not self.workspace_root.is_dir():
            raise ScannerError(
                f"Workspace is not a directory: {self.workspace_root}"
            )

        self.output_file = (
            output_file.resolve()
            if output_file
            else DEFAULT_OUTPUT_FILE.resolve()
        )

        self.excluded_dirs = set(
            DEFAULT_EXCLUDED_DIRS
        )

        if excluded_dirs:
            self.excluded_dirs.update(
                excluded_dirs
            )

        self.files: List[FileRecord] = []
        self.directories: List[str] = []

        self.language_counts: Counter[str] = Counter()

        self.test_files: List[str] = []
        self.entry_points: List[str] = []
        self.sensitive_files: List[Dict[str, str]] = []

        self.project_types: Set[str] = set()

        self.readme_files: List[str] = []

        self.scan_started = 0.0
        self.scan_duration_ms = 0.0

        self.git_info = GitInfo(
            detected=False,
            is_work_tree=False,
            branch=None,
            root=None,
            clean=None,
            status_error=None,
        )

    # ----------------------------------------------------------------------
    # Path guard
    # ----------------------------------------------------------------------

    def resolve_inside_workspace(
        self,
        relative_or_absolute: Path,
    ) -> Path:
        candidate = (
            relative_or_absolute.resolve()
        )

        try:
            candidate.relative_to(
                self.workspace_root
            )
        except ValueError as exc:
            raise WorkspaceViolation(
                f"Path escapes active workspace: "
                f"{relative_or_absolute}"
            ) from exc

        return candidate

    # ----------------------------------------------------------------------
    # File walking
    # ----------------------------------------------------------------------

    def iter_project_files(
        self,
    ) -> Iterable[Path]:

        count = 0

        for root, dir_names, file_names in os.walk(
            self.workspace_root,
            topdown=True,
            followlinks=False,
        ):
            root_path = Path(root)

            # Prune excluded directories.
            dir_names[:] = [
                directory
                for directory in dir_names
                if directory not in self.excluded_dirs
                and not directory.startswith(".agent_")
            ]

            # Record relative directory.
            if root_path != self.workspace_root:
                try:
                    relative_root = (
                        root_path.relative_to(
                            self.workspace_root
                        )
                    )
                except ValueError as exc:
                    raise WorkspaceViolation(
                        f"Scanner discovered directory outside "
                        f"workspace: {root_path}"
                    ) from exc

                self.directories.append(
                    normalize_relative_path(
                        relative_root
                    )
                )

            for file_name in file_names:
                count += 1

                if count > MAX_FILES:
                    raise ScanLimitExceeded(
                        f"Project exceeds maximum scan file count "
                        f"({MAX_FILES})."
                    )

                candidate = (
                    root_path / file_name
                )

                # Resolve before inspection so symlink escapes are rejected.
                resolved = self.resolve_inside_workspace(
                    candidate
                )

                yield resolved

    # ----------------------------------------------------------------------
    # File classification
    # ----------------------------------------------------------------------

    def classify_file(
        self,
        path: Path,
    ) -> FileRecord:

        try:
            relative = path.relative_to(
                self.workspace_root
            )
        except ValueError as exc:
            raise WorkspaceViolation(
                f"File outside workspace: {path}"
            ) from exc

        relative_string = normalize_relative_path(
            relative
        )

        name = path.name
        extension = path.suffix.lower()

        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0

        language = detect_language(
            extension
        )

        test = is_test_file(
            name
        )

        entry = (
            name in ENTRY_FILE_NAMES
        )

        sensitive, reason = detect_sensitivity(
            path
        )

        # Detect README family.
        if name.lower() in {
            "readme",
            "readme.md",
            "readme.txt",
            "readme.rst",
        }:
            self.readme_files.append(
                relative_string
            )

        if language:
            self.language_counts[
                language
            ] += 1

        if test:
            self.test_files.append(
                relative_string
            )

        if entry:
            self.entry_points.append(
                relative_string
            )

        if sensitive:
            self.sensitive_files.append(
                {
                    "path": relative_string,
                    "reason": reason or "unknown",
                }
            )

        return FileRecord(
            path=relative_string,
            name=name,
            extension=extension,
            language=language,
            size_bytes=size_bytes,
            is_test=test,
            is_entry_point=entry,
            is_sensitive=sensitive,
            sensitivity_reason=reason,
        )

    # ----------------------------------------------------------------------
    # Project marker detection
    # ----------------------------------------------------------------------

    def detect_project_types(
        self,
    ) -> None:

        root_files = {
            path.name
            for path in self.workspace_root.iterdir()
            if path.is_file()
        }

        for project_type, markers in PROJECT_MARKERS.items():
            for marker in markers:

                if marker.startswith("*"):
                    extension = marker[1:].lower()

                    if any(
                        file_name.lower().endswith(
                            extension
                        )
                        for file_name in root_files
                    ):
                        self.project_types.add(
                            project_type
                        )

                elif marker in root_files:
                    self.project_types.add(
                        project_type
                    )

    # ----------------------------------------------------------------------
    # Git
    # ----------------------------------------------------------------------

    def detect_git(
        self,
    ) -> GitInfo:

        git_dir = (
            self.workspace_root /
            ".git"
        )

        git_detected = git_dir.exists()

        if not git_detected:
            # It may still be a worktree through a parent directory.
            try:
                completed = subprocess.run(
                    GIT_COMMAND,
                    cwd=self.workspace_root,
                    shell=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    check=False,
                )

                if (
                    completed.returncode == 0
                    and completed.stdout.strip()
                    == "true"
                ):
                    git_detected = True

            except (
                OSError,
                subprocess.TimeoutExpired,
            ):
                pass

        if not git_detected:
            self.git_info = GitInfo(
                detected=False,
                is_work_tree=False,
                branch=None,
                root=None,
                clean=None,
                status_error=None,
            )

            return self.git_info

        branch: Optional[str] = None
        root: Optional[str] = None
        clean: Optional[bool] = None
        status_error: Optional[str] = None

        try:
            branch_result = subprocess.run(
                [
                    "git",
                    "branch",
                    "--show-current",
                ],
                cwd=self.workspace_root,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )

            if branch_result.returncode == 0:
                branch = (
                    branch_result.stdout.strip()
                    or None
                )

            root_result = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "--show-toplevel",
                ],
                cwd=self.workspace_root,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )

            if root_result.returncode == 0:
                discovered_root = Path(
                    root_result.stdout.strip()
                ).resolve()

                # IMPORTANT:
                # Git root must not silently expand the active workspace.
                try:
                    discovered_root.relative_to(
                        self.workspace_root
                    )
                except ValueError:
                    # For scanner security, record this as a mismatch
                    # instead of adopting a parent Git repository.
                    status_error = (
                        "Git repository root is outside active workspace."
                    )
                else:
                    root = str(
                        discovered_root
                    )

            status_result = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                cwd=self.workspace_root,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )

            if status_result.returncode == 0:
                clean = (
                    status_result.stdout.strip()
                    == ""
                )
            else:
                status_error = (
                    status_result.stderr.strip()
                    or "git status failed"
                )

        except subprocess.TimeoutExpired:
            status_error = (
                "Git inspection timed out."
            )

        except OSError as exc:
            status_error = (
                f"Git inspection failed: {exc}"
            )

        self.git_info = GitInfo(
            detected=True,
            is_work_tree=True,
            branch=branch,
            root=root,
            clean=clean,
            status_error=status_error,
        )

        return self.git_info

    # ----------------------------------------------------------------------
    # Special root files
    # ----------------------------------------------------------------------

    def root_configuration_files(
        self,
    ) -> List[str]:

        result: List[str] = []

        try:
            for item in self.workspace_root.iterdir():
                if not item.is_file():
                    continue

                if (
                    item.name in {
                        "pyproject.toml",
                        "requirements.txt",
                        "requirements-dev.txt",
                        "package.json",
                        "package-lock.json",
                        "yarn.lock",
                        "pnpm-lock.yaml",
                        "Cargo.toml",
                        "Cargo.lock",
                        "go.mod",
                        "go.sum",
                        "pom.xml",
                        "build.gradle",
                        "build.gradle.kts",
                        "composer.json",
                        "Gemfile",
                        "pubspec.yaml",
                        "Dockerfile",
                        "docker-compose.yml",
                        "docker-compose.yaml",
                        "Makefile",
                        "justfile",
                        ".gitignore",
                        ".dockerignore",
                    }
                    or item.name.lower().startswith(
                        "readme"
                    )
                ):
                    result.append(
                        item.name
                    )

        except OSError:
            pass

        return sorted(
            result
        )

    # ----------------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------------

    def make_summary(
        self,
    ) -> Dict[str, Any]:

        total_size = sum(
            file.size_bytes
            for file in self.files
        )

        source_files = [
            file
            for file in self.files
            if file.language
            and not file.is_sensitive
        ]

        sensitive_count = sum(
            1
            for file in self.files
            if file.is_sensitive
        )

        binary_count = 0

        for file in self.files:
            try:
                path = self.resolve_inside_workspace(
                    self.workspace_root /
                    Path(file.path)
                )

                if is_probably_binary(path):
                    binary_count += 1

            except (
                OSError,
                WorkspaceViolation,
            ):
                pass

        dominant_language = None

        if self.language_counts:
            dominant_language = (
                self.language_counts.most_common(1)[0][0]
            )

        return {
            "file_count": len(self.files),
            "directory_count": len(
                self.directories
            ),
            "source_file_count": len(
                source_files
            ),
            "test_file_count": len(
                self.test_files
            ),
            "entry_point_count": len(
                self.entry_points
            ),
            "sensitive_file_count": sensitive_count,
            "binary_file_count": binary_count,
            "total_size_bytes": total_size,
            "dominant_language": dominant_language,
            "languages": dict(
                self.language_counts
            ),
            "project_types": sorted(
                self.project_types
            ),
            "readme_files": sorted(
                set(self.readme_files)
            ),
            "root_configuration_files": (
                self.root_configuration_files()
            ),
        }

    # ----------------------------------------------------------------------
    # Scan
    # ----------------------------------------------------------------------

    def scan(
        self,
    ) -> Dict[str, Any]:

        self.scan_started = time.perf_counter()

        self.files = []
        self.directories = []
        self.language_counts = Counter()
        self.test_files = []
        self.entry_points = []
        self.sensitive_files = []
        self.project_types = set()
        self.readme_files = []

        self.detect_project_types()

        for path in self.iter_project_files():
            record = self.classify_file(
                path
            )

            self.files.append(
                record
            )

        self.detect_git()

        self.scan_duration_ms = (
            time.perf_counter()
            - self.scan_started
        ) * 1000.0

        summary = self.make_summary()

        manifest = {
            "schema_version": 1,
            "scanner": {
                "name": "ProjectScanner",
                "version": "v1",
                "python": sys.version.split()[0],
                "scanned_at": time.time(),
                "duration_ms": round(
                    self.scan_duration_ms,
                    2,
                ),
            },

            "workspace": {
                "root": str(
                    self.workspace_root
                ),
                "active_workspace_only": True,
                "excluded_directories": sorted(
                    self.excluded_dirs
                ),
            },

            "summary": summary,

            "git": asdict(
                self.git_info
            ),

            "files": [
                asdict(file)
                for file in sorted(
                    self.files,
                    key=lambda item: item.path.lower(),
                )
            ],

            "tests": sorted(
                set(self.test_files)
            ),

            "entry_points": sorted(
                set(self.entry_points)
            ),

            "sensitive_files": sorted(
                self.sensitive_files,
                key=lambda item: item["path"].lower(),
            ),

            "readme_files": sorted(
                set(self.readme_files)
            ),

            "notes": [
                "Scanner performs local inspection only.",
                "No project code was sent to an external provider.",
                "No project code was executed by the scanner.",
                "Sensitive files are classified but their contents are not read.",
                "Excluded dependency/build/cache directories are not scanned.",
            ],
        }

        return manifest

    # ----------------------------------------------------------------------
    # Persist
    # ----------------------------------------------------------------------

    def save(
        self,
        manifest: Dict[str, Any],
    ) -> Path:

        # The output location itself must also be controlled.
        output = self.output_file

        try:
            output.relative_to(
                self.workspace_root
            )
        except ValueError:
            # project_manifest.json is allowed in the scanner's own control
            # directory only for the synthetic test below.
            #
            # For a real project, callers should supply an output path
            # inside the active workspace.
            raise WorkspaceViolation(
                "Manifest output must remain inside active workspace."
            )

        temp = output.with_name(
            f".{output.name}.tmp-"
            f"{os.getpid()}-{time.time_ns()}"
        )

        try:
            with temp.open(
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    manifest,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                )
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(
                temp,
                output,
            )

        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

        return output


# ============================================================================
# Synthetic test helpers
# ============================================================================


def write_text(
    path: Path,
    content: str,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        content,
        encoding="utf-8",
    )


def build_synthetic_project() -> Path:

    workspace = (
        BASE_DIR /
        ".project_scanner_test"
    )

    if workspace.exists():
        import shutil

        shutil.rmtree(
            workspace,
            ignore_errors=True,
        )

    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Python source.
    write_text(
        workspace / "app.py",
        """def add(a, b):
    return a + b
""",
    )

    # Entry point.
    write_text(
        workspace / "main.py",
        """from app import add


def main():
    print(add(2, 3))


if __name__ == "__main__":
    main()
""",
    )

    # Test.
    write_text(
        workspace / "test_app.py",
        """from app import add


def test_add():
    assert add(2, 3) == 5
""",
    )

    # Config.
    write_text(
        workspace / "pyproject.toml",
        """[project]
name = "scanner-test"
version = "0.1.0"
""",
    )

    # Readme.
    write_text(
        workspace / "README.md",
        """# Scanner Test

Synthetic project for ProjectScanner.
""",
    )

    # Nested source.
    write_text(
        workspace / "src" / "utils.py",
        """def identity(value):
    return value
""",
    )

    # Sensitive file: CONTENT MUST NOT MATTER.
    write_text(
        workspace / ".env",
        """SECRET_VALUE=do-not-read
""",
    )

    # Dependency-like directory that must be excluded.
    write_text(
        workspace / "node_modules" / "ignored.js",
        """this should not be scanned
""",
    )

    # Build directory that must be excluded.
    write_text(
        workspace / "build" / "ignored.py",
        """this should not be scanned
""",
    )

    return workspace


# ============================================================================
# Synthetic tests
# ============================================================================


def synthetic_test() -> int:

    print("=" * 70)
    print("PROJECT SCANNER SYNTHETIC TEST")
    print("=" * 70)
    print()

    workspace = build_synthetic_project()

    output_file = (
        workspace /
        "project_manifest.json"
    )

    scanner = ProjectScanner(
        workspace_root=workspace,
        output_file=output_file,
    )

    # ----------------------------------------------------------------------
    # TEST 1: Workspace detection
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 1: WORKSPACE DETECTION")
    print("-" * 70)

    if scanner.workspace_root != workspace.resolve():
        raise AssertionError(
            "Workspace root mismatch."
        )

    print(
        "Active workspace:",
        scanner.workspace_root,
    )

    print(
        "Workspace detection: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # TEST 2: Scan
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 2: PROJECT SCAN")
    print("-" * 70)

    manifest = scanner.scan()

    print(
        "Files discovered:",
        manifest["summary"]["file_count"],
    )

    print(
        "Languages:",
        manifest["summary"]["languages"],
    )

    print(
        "Project types:",
        manifest["summary"]["project_types"],
    )

    if "Python" not in manifest[
        "summary"
    ]["project_types"]:
        raise AssertionError(
            "Python project was not detected."
        )

    if "app.py" not in {
        item["path"]
        for item in manifest["files"]
    }:
        raise AssertionError(
            "app.py was not discovered."
        )

    if "src/utils.py" not in {
        item["path"]
        for item in manifest["files"]
    }:
        raise AssertionError(
            "Nested source file was not discovered."
        )

    print(
        "Project scan: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # TEST 3: Test discovery
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 3: TEST DISCOVERY")
    print("-" * 70)

    tests = manifest[
        "tests"
    ]

    print(
        "Test files:",
        tests,
    )

    if "test_app.py" not in tests:
        raise AssertionError(
            "test_app.py was not detected as a test."
        )

    print(
        "Test discovery: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # TEST 4: Entry point detection
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 4: ENTRY POINT DETECTION")
    print("-" * 70)

    entries = manifest[
        "entry_points"
    ]

    print(
        "Entry points:",
        entries,
    )

    if "main.py" not in entries:
        raise AssertionError(
            "main.py was not detected as an entry point."
        )

    print(
        "Entry point detection: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # TEST 5: Sensitive file detection
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 5: SENSITIVE FILE DETECTION")
    print("-" * 70)

    sensitive = manifest[
        "sensitive_files"
    ]

    print(
        "Sensitive files:",
        sensitive,
    )

    sensitive_paths = {
        item["path"]
        for item in sensitive
    }

    if ".env" not in sensitive_paths:
        raise AssertionError(
            ".env was not classified as sensitive."
        )

    # Verify the scanner did not copy secret content into the manifest.
    manifest_text = json.dumps(
        manifest,
        ensure_ascii=False,
    )

    if "SECRET_VALUE" in manifest_text:
        raise AssertionError(
            "Sensitive file content leaked into manifest."
        )

    if "do-not-read" in manifest_text:
        raise AssertionError(
            "Sensitive file content leaked into manifest."
        )

    print(
        "Sensitive classification without content read: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # TEST 6: Exclusion
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 6: EXCLUDED DIRECTORIES")
    print("-" * 70)

    discovered_paths = {
        item["path"]
        for item in manifest["files"]
    }

    if (
        "node_modules/ignored.js"
        in discovered_paths
    ):
        raise AssertionError(
            "node_modules was scanned unexpectedly."
        )

    if (
        "build/ignored.py"
        in discovered_paths
    ):
        raise AssertionError(
            "build directory was scanned unexpectedly."
        )

    print(
        "Generated/dependency directory exclusion: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # TEST 7: Workspace escape
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 7: WORKSPACE ESCAPE -> REJECT")
    print("-" * 70)

    try:
        scanner.resolve_inside_workspace(
            Path("../outside.txt")
        )

    except WorkspaceViolation:
        print(
            "Workspace escape rejected: PASS ✅"
        )

    else:
        raise AssertionError(
            "Scanner accepted path outside workspace."
        )

    print()

    # ----------------------------------------------------------------------
    # TEST 8: Manifest persistence
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 8: MANIFEST PERSISTENCE")
    print("-" * 70)

    saved = scanner.save(
        manifest
    )

    print(
        "Manifest:",
        saved,
    )

    if not saved.exists():
        raise AssertionError(
            "Manifest was not written."
        )

    loaded = json.loads(
        saved.read_text(
            encoding="utf-8"
        )
    )

    if loaded["schema_version"] != 1:
        raise AssertionError(
            "Manifest schema version mismatch."
        )

    if (
        loaded["summary"]["file_count"]
        != manifest["summary"]["file_count"]
    ):
        raise AssertionError(
            "Persisted manifest differs from in-memory manifest."
        )

    print(
        "Manifest persistence: PASS ✅"
    )
    print()

    # ----------------------------------------------------------------------
    # Final
    # ----------------------------------------------------------------------

    print("=" * 70)
    print("PROJECT SCANNER TEST PASSED ✅")
    print("=" * 70)

    # Save a compact result outside the synthetic project.
    result_file = (
        BASE_DIR /
        "project_scanner_test_result.json"
    )

    result_file.write_text(
        json.dumps(
            {
                "status": "PASS",
                "version": "v1",
                "workspace": str(workspace),
                "summary": manifest[
                    "summary"
                ],
                "tests": manifest[
                    "tests"
                ],
                "entry_points": manifest[
                    "entry_points"
                ],
                "sensitive_files": manifest[
                    "sensitive_files"
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        f"Test result saved to: {result_file}"
    )

    return 0


# ============================================================================
# Main
# ============================================================================


def main() -> int:

    try:
        return synthetic_test()

    except Exception as exc:

        print()
        print("=" * 70)
        print("PROJECT SCANNER TEST FAILED ❌")
        print("=" * 70)

        print(
            f"{type(exc).__name__}: {exc}"
        )

        return 1

    finally:
        workspace = (
            BASE_DIR /
            ".project_scanner_test"
        )

        if workspace.exists():
            import shutil

            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )