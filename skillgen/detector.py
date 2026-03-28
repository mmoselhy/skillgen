"""Language and framework detection by scanning file extensions and config files."""

from __future__ import annotations

import os
from pathlib import Path

from skillgen.models import (
    FrameworkInfo,
    Language,
    LanguageInfo,
    ProjectInfo,
)

# Directories to always skip (case-sensitive).
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "__pycache__",
        "build",
        "dist",
        "target",
        ".tox",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        ".nuxt",
        "coverage",
        ".eggs",
        "egg-info",
        ".ruff_cache",
        ".cache",
    }
)

# Extension -> language value mapping (derived from Language.extensions to avoid drift).
EXTENSION_MAP: dict[str, str] = {ext: lang.value for lang in Language for ext in lang.extensions}

# Manifest file -> language value mapping.
MANIFEST_MAP: dict[str, str | None] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "CMakeLists.txt": "cpp",
}

# Framework detection: (filename_or_keyword, framework_name, language_value).
FRAMEWORK_MARKERS: list[tuple[str, str, str]] = [
    # Python
    ("manage.py", "Django", "python"),
    ("django", "Django", "python"),
    ("flask", "Flask", "python"),
    ("fastapi", "FastAPI", "python"),
    ("starlette", "Starlette", "python"),
    # TypeScript / JavaScript
    ("next.config.js", "Next.js", "typescript"),
    ("next.config.mjs", "Next.js", "typescript"),
    ("next.config.ts", "Next.js", "typescript"),
    ("nuxt.config.ts", "Nuxt", "typescript"),
    ("angular.json", "Angular", "typescript"),
    ("svelte.config.js", "Svelte", "javascript"),
    ("remix.config.js", "Remix", "typescript"),
    ("vue", "Vue", "javascript"),
    ("react", "React", "javascript"),
    # Java
    ("spring", "Spring", "java"),
    ("quarkus", "Quarkus", "java"),
    # Go
    ("gin", "Gin", "go"),
    ("echo", "Echo", "go"),
    ("fiber", "Fiber", "go"),
    # Rust
    ("actix", "Actix", "rust"),
    ("axum", "Axum", "rust"),
    ("rocket", "Rocket", "rust"),
    ("tokio", "Tokio", "rust"),
]


def detect_project(root: Path, verbose: bool = False) -> ProjectInfo:
    """Scan the project directory and return a ProjectInfo."""
    lang_counts: dict[str, int] = {}
    lang_files: dict[str, list[Path]] = {}
    manifest_paths: list[Path] = []
    config_files: list[Path] = []
    total_files_ref: list[int] = [0]

    _scan_directory(
        root, root, lang_counts, lang_files, manifest_paths, config_files, total_files_ref
    )
    total_files = total_files_ref[0]

    # If tsconfig.json present, reclassify javascript as typescript
    manifest_names = {p.name for p in manifest_paths}
    if "tsconfig.json" in manifest_names:
        js_count = lang_counts.pop("javascript", 0)
        js_files = lang_files.pop("javascript", [])
        if js_count > 0:
            lang_counts["typescript"] = lang_counts.get("typescript", 0) + js_count
            lang_files.setdefault("typescript", []).extend(js_files)

    source_files = sum(lang_counts.values())

    # Build LanguageInfo list, filtering by >=10% threshold
    languages: list[LanguageInfo] = []
    if source_files > 0:
        for lang_val, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
            pct = (count / source_files) * 100
            if pct >= 10.0:
                try:
                    lang_enum = Language(lang_val)
                except ValueError:
                    continue
                languages.append(
                    LanguageInfo(
                        language=lang_enum,
                        file_count=count,
                        file_paths=lang_files.get(lang_val, []),
                        percentage=round(pct, 1),
                    )
                )

    # Detect frameworks
    frameworks = _detect_frameworks(manifest_paths, root, manifest_names)

    return ProjectInfo(
        root_path=root,
        languages=languages,
        frameworks=frameworks,
        total_files=total_files,
        source_files=source_files,
        config_files=config_files,
        manifest_files=manifest_paths,
    )


def _scan_directory(
    root: Path,
    current: Path,
    lang_counts: dict[str, int],
    lang_files: dict[str, list[Path]],
    manifest_paths: list[Path],
    config_files: list[Path],
    total_files_ref: list[int],
) -> None:
    """Recursively scan directory, populating counts and paths."""
    try:
        entries = list(os.scandir(current))
    except PermissionError:
        return

    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            if entry.name in SKIP_DIRS:
                continue
            _scan_directory(
                root,
                Path(entry.path),
                lang_counts,
                lang_files,
                manifest_paths,
                config_files,
                total_files_ref,
            )
        elif entry.is_file(follow_symlinks=False):
            total_files_ref[0] += 1
            file_path = Path(entry.path)
            name = entry.name
            ext = _get_extension(name)

            # Check if it's a manifest file
            if name in MANIFEST_MAP:
                manifest_paths.append(file_path)

            # Check for config files
            if name in (
                ".editorconfig",
                ".eslintrc",
                ".eslintrc.js",
                ".eslintrc.json",
                ".prettierrc",
                ".prettierrc.json",
                "prettier.config.js",
                "rustfmt.toml",
                ".flake8",
                "ruff.toml",
                ".isort.cfg",
                ".pylintrc",
                "mypy.ini",
                "tox.ini",
                ".golangci.yml",
                ".golangci.yaml",
            ):
                config_files.append(file_path)

            # Count by language
            if ext in EXTENSION_MAP:
                lang_val = EXTENSION_MAP[ext]
                lang_counts[lang_val] = lang_counts.get(lang_val, 0) + 1
                lang_files.setdefault(lang_val, []).append(file_path)


def _get_extension(filename: str) -> str:
    """Get file extension, lowercased."""
    dot_idx = filename.rfind(".")
    if dot_idx <= 0:
        return ""
    return filename[dot_idx:].lower()


def _detect_frameworks(
    manifest_paths: list[Path],
    root: Path,
    manifest_names: set[str],
) -> list[FrameworkInfo]:
    """Read manifest contents and match against FRAMEWORK_MARKERS."""
    frameworks: list[FrameworkInfo] = []
    seen_frameworks: set[str] = set()

    # Check for file-based markers (files that exist in the root or project)
    for marker, fw_name, lang_val in FRAMEWORK_MARKERS:
        if fw_name in seen_frameworks:
            continue

        # Check if marker matches a filename in the project root
        marker_path = root / marker
        if marker_path.is_file():
            try:
                lang_enum = Language(lang_val)
            except ValueError:
                continue
            frameworks.append(
                FrameworkInfo(
                    name=fw_name,
                    language=lang_enum,
                    evidence=f"{marker} found in project root",
                )
            )
            seen_frameworks.add(fw_name)
            continue

    # Check manifest file contents for keyword-based markers
    for manifest_path in manifest_paths:
        try:
            content = manifest_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        content_lower = content.lower()
        for marker, fw_name, lang_val in FRAMEWORK_MARKERS:
            if fw_name in seen_frameworks:
                continue
            # Only do keyword search for non-filename markers
            if "." not in marker and "/" not in marker and marker.lower() in content_lower:
                try:
                    lang_enum = Language(lang_val)
                except ValueError:
                    continue
                frameworks.append(
                    FrameworkInfo(
                        name=fw_name,
                        language=lang_enum,
                        evidence=f"'{marker}' found in {manifest_path.name}",
                    )
                )
                seen_frameworks.add(fw_name)

    return frameworks
