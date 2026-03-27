"""Code pattern analysis using regex-based extraction."""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from skillgen.detector import SKIP_DIRS
from skillgen.models import (
    AnalysisResult,
    CodePattern,
    Confidence,
    Language,
    PatternCategory,
    ProjectInfo,
)

# Maximum files to sample per language.
MAX_SAMPLE_FILES = 50
# Maximum files from a single directory.
MAX_PER_DIR = 5


def analyze_project(
    project_info: ProjectInfo,
    verbose: bool = False,
    use_tree_sitter: bool = True,
) -> AnalysisResult:
    """Analyze the project and extract code patterns.

    When use_tree_sitter is True and tree-sitter is installed, uses AST-based
    extraction for more accurate pattern detection. Falls back to regex
    per-language when a specific grammar is unavailable.
    """
    from skillgen.ts_parser import TREE_SITTER_AVAILABLE, is_language_available

    start = time.monotonic()
    all_patterns: list[CodePattern] = []
    files_analyzed = 0
    files_skipped = 0

    # Determine which languages can use tree-sitter
    ts_enabled = use_tree_sitter and TREE_SITTER_AVAILABLE
    ts_langs: set[Language] = set()
    if ts_enabled:
        from skillgen.ts_extractors import ts_extract_all
        from skillgen.ts_parser import parse_source

        for lang_info in project_info.languages:
            if is_language_available(lang_info.language):
                ts_langs.add(lang_info.language)

    # Regex extractors (same signature for all 7 categories)
    regex_extractors = [
        _extract_naming, _extract_error_handling, _extract_testing,
        _extract_imports, _extract_documentation, _extract_style, _extract_logging,
    ]

    for lang_info in project_info.languages:
        sample = _select_sample(lang_info.file_paths, MAX_SAMPLE_FILES, MAX_PER_DIR)
        for file_path in sample:
            try:
                source = file_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                files_skipped += 1
                continue

            if not source.strip():
                files_skipped += 1
                continue

            files_analyzed += 1
            lang = lang_info.language

            if lang in ts_langs:
                root = parse_source(source, lang, file_path)
                if root is not None:
                    all_patterns.extend(ts_extract_all(root, source, lang, file_path))
                else:
                    # Parse failed — fall back to regex
                    for extractor in regex_extractors:
                        all_patterns.extend(extractor(source, lang, file_path))
            else:
                for extractor in regex_extractors:
                    all_patterns.extend(extractor(source, lang, file_path))

    # Architecture patterns from directory structure
    all_patterns.extend(_extract_architecture(project_info))

    elapsed = time.monotonic() - start
    return AnalysisResult(
        project_info=project_info,
        patterns=all_patterns,
        files_analyzed=files_analyzed,
        files_skipped=files_skipped,
        analysis_duration_seconds=elapsed,
    )


def _select_sample(files: list[Path], max_files: int = 50, max_per_dir: int = 5) -> list[Path]:
    """Select a diverse sample of files from different directories."""
    if len(files) <= max_files:
        return files

    # Group by parent directory
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for f in files:
        by_dir[f.parent].append(f)

    # Sort directories by file count (descending) for diversity
    sorted_dirs = sorted(by_dir.items(), key=lambda x: -len(x[1]))

    selected: list[Path] = []
    # First pass: take up to max_per_dir from each directory
    for _dir_path, dir_files in sorted_dirs:
        # Prefer larger files (more patterns)
        sorted_files = sorted(dir_files, key=lambda f: _safe_file_size(f), reverse=True)
        for f in sorted_files[:max_per_dir]:
            if len(selected) >= max_files:
                break
            selected.append(f)
        if len(selected) >= max_files:
            break

    return selected


def _safe_file_size(path: Path) -> int:
    """Get file size, returning 0 on error."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


# --- Naming Convention Extraction ---

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
_CAMEL_CASE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
_PASCAL_CASE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")


def _classify_name(name: str) -> str | None:
    """Classify an identifier's naming convention."""
    if _UPPER_SNAKE.match(name):
        return "UPPER_SNAKE_CASE"
    if _SNAKE_CASE.match(name):
        return "snake_case"
    if _PASCAL_CASE.match(name):
        return "PascalCase"
    if _CAMEL_CASE.match(name) and not name.islower():
        return "camelCase"
    if name.islower() and "_" not in name and len(name) > 1:
        return "snake_case"  # single-word lowercase is compatible with snake_case
    return None


def _extract_naming(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract naming convention patterns."""
    patterns: list[CodePattern] = []
    func_names: list[str] = []
    class_names: list[str] = []

    if lang in (Language.PYTHON,):
        func_names = re.findall(r"def\s+([a-zA-Z_]\w*)\s*\(", source)
        class_names = re.findall(r"class\s+([a-zA-Z_]\w*)", source)
    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        func_names = re.findall(r"function\s+([a-zA-Z_$]\w*)", source)
        func_names += re.findall(
            r"(?:const|let|var)\s+([a-zA-Z_$]\w*)\s*=\s*(?:async\s*)?\(", source
        )
        class_names = re.findall(r"class\s+([a-zA-Z_$]\w*)", source)
    elif lang == Language.JAVA:
        func_names = re.findall(
            r"(?:public|private|protected|static)\s+\w+\s+([a-zA-Z_]\w*)\s*\(", source
        )
        class_names = re.findall(r"class\s+([A-Z]\w*)", source)
    elif lang == Language.GO:
        func_names = re.findall(r"func\s+(?:\([^)]*\)\s*)?([a-zA-Z_]\w*)\s*\(", source)
        class_names = re.findall(r"type\s+([A-Z]\w*)\s+struct", source)
    elif lang == Language.RUST:
        func_names = re.findall(r"fn\s+([a-zA-Z_]\w*)\s*[(<]", source)
        class_names = re.findall(r"struct\s+([A-Z]\w*)", source)
        class_names += re.findall(r"enum\s+([A-Z]\w*)", source)
    elif lang == Language.CPP:
        func_names = re.findall(r"\b(?:void|int|bool|auto|string)\s+([a-zA-Z_]\w*)\s*\(", source)
        class_names = re.findall(r"class\s+([A-Z]\w*)", source)

    # Filter out common special names
    func_names = [n for n in func_names if not n.startswith("__") and n not in ("main", "init")]

    # Classify function naming
    func_styles: Counter[str] = Counter()
    func_evidence: dict[str, list[str]] = defaultdict(list)
    for name in func_names:
        style = _classify_name(name)
        if style and style != "UPPER_SNAKE_CASE":
            func_styles[style] += 1
            if len(func_evidence[style]) < 3:
                func_evidence[style].append(f"{name} ({file_path.name})")

    if func_styles:
        total = sum(func_styles.values())
        for style, count in func_styles.most_common():
            prevalence = count / total if total > 0 else 0.0
            confidence = (
                Confidence.HIGH
                if prevalence > 0.8
                else (Confidence.MEDIUM if prevalence > 0.5 else Confidence.LOW)
            )
            conflict = None
            if prevalence < 0.9 and len(func_styles) > 1:
                others = [
                    f"{c / total:.0%} use {s}" for s, c in func_styles.most_common() if s != style
                ]
                conflict = ", ".join(others)

            patterns.append(
                CodePattern(
                    category=PatternCategory.NAMING,
                    name="function_naming",
                    description=f"Functions use {style}",
                    evidence=func_evidence.get(style, []),
                    confidence=confidence,
                    prevalence=prevalence,
                    language=lang,
                    file_path=file_path,
                    conflict=conflict,
                )
            )
            break  # Only report the dominant style per file

    # Classify class naming
    class_styles: Counter[str] = Counter()
    class_evidence: list[str] = []
    for name in class_names:
        style = _classify_name(name)
        if style:
            class_styles[style] += 1
            if len(class_evidence) < 3:
                class_evidence.append(f"{name} ({file_path.name})")

    if class_styles:
        dominant_style = class_styles.most_common(1)[0][0]
        total = sum(class_styles.values())
        patterns.append(
            CodePattern(
                category=PatternCategory.NAMING,
                name="class_naming",
                description=f"Classes/types use {dominant_style}",
                evidence=class_evidence,
                confidence=Confidence.HIGH
                if class_styles[dominant_style] / total > 0.8
                else Confidence.MEDIUM,
                prevalence=class_styles[dominant_style] / total,
                language=lang,
                file_path=file_path,
            )
        )

    return patterns


# --- Error Handling Extraction ---


def _extract_error_handling(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract error handling patterns."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        # Try/except patterns
        except_types = re.findall(r"except\s+(\w+)", source)
        if except_types:
            evidence = [f"except {t}" for t in except_types[:5]]
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="exception_types",
                    description=f"Uses try/except with types: {', '.join(set(except_types[:5]))}",
                    evidence=evidence,
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Custom exception classes
        custom_exceptions = re.findall(r"class\s+(\w+)\(.*(?:Exception|Error)\)", source)
        if custom_exceptions:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="custom_exceptions",
                    description=f"Defines custom exceptions: {', '.join(custom_exceptions[:3])}",
                    evidence=[f"class {e}" for e in custom_exceptions[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Raise patterns
        raise_types = re.findall(r"raise\s+(\w+)", source)
        if raise_types:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="raise_style",
                    description=f"Raises: {', '.join(set(raise_types[:5]))}",
                    evidence=[f"raise {t}" for t in raise_types[:3]],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # Try/catch
        catches = re.findall(r"catch\s*\((\w+)\)", source)
        if catches:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="try_catch",
                    description="Uses try/catch blocks for error handling",
                    evidence=[f"catch ({c})" for c in catches[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Custom error classes
        custom_errors = re.findall(r"class\s+(\w+)\s+extends\s+Error", source)
        if custom_errors:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="custom_errors",
                    description=f"Custom error classes: {', '.join(custom_errors[:3])}",
                    evidence=[f"class {e} extends Error" for e in custom_errors[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.GO:
        # if err != nil
        err_checks = re.findall(r"if\s+err\s*!=\s*nil", source)
        if err_checks:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="err_nil_check",
                    description=f"Uses 'if err != nil' pattern ({len(err_checks)} occurrences)",
                    evidence=["if err != nil { ... }"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # fmt.Errorf wrapping
        errorf_calls = re.findall(r'fmt\.Errorf\("([^"]*)"', source)
        if errorf_calls:
            has_wrap = any("%w" in e for e in errorf_calls)
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="error_wrapping",
                    description="Wraps errors with fmt.Errorf" + (" using %w" if has_wrap else ""),
                    evidence=[f'fmt.Errorf("{e}")' for e in errorf_calls[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.RUST:
        # Result type usage
        result_types = re.findall(r"Result<([^>]+)>", source)
        if result_types:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="result_type",
                    description="Uses Result<T, E> for error handling",
                    evidence=[f"Result<{r}>" for r in result_types[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Question mark operator
        qmark_count = source.count("?;") + source.count("?\n")
        if qmark_count > 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="question_mark_operator",
                    description=f"Uses ? operator for error propagation ({qmark_count} occurrences)",
                    evidence=["Uses ? for early return on error"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Unwrap usage
        unwrap_count = len(re.findall(r"\.unwrap\(\)", source))
        if unwrap_count > 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="unwrap_usage",
                    description=f".unwrap() used {unwrap_count} times (consider expect() or ?)",
                    evidence=[".unwrap()"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.JAVA:
        # Try/catch
        catch_types = re.findall(r"catch\s*\(\s*(\w+)", source)
        if catch_types:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="catch_types",
                    description=f"Catches: {', '.join(set(catch_types[:5]))}",
                    evidence=[f"catch ({t})" for t in catch_types[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    return patterns


# --- Testing Pattern Extraction ---


def _extract_testing(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract testing patterns."""
    patterns: list[CodePattern] = []
    fname = file_path.name.lower()

    # Determine if this is a test file
    is_test = False
    if lang == Language.PYTHON:
        is_test = fname.startswith("test_") or fname.endswith("_test.py") or "conftest" in fname
    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        is_test = ".test." in fname or ".spec." in fname or "__tests__" in str(file_path)
    elif lang == Language.GO:
        is_test = fname.endswith("_test.go")
    elif lang == Language.RUST:
        is_test = "#[cfg(test)]" in source or "#[test]" in source
    elif lang == Language.JAVA:
        is_test = "Test" in fname or "@Test" in source

    if not is_test:
        return patterns

    if lang == Language.PYTHON:
        # Detect pytest vs unittest
        if "import pytest" in source or "@pytest" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="test_framework",
                    description="Uses pytest as the test framework",
                    evidence=["import pytest"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

            # Fixture usage
            fixtures = re.findall(r"@pytest\.fixture", source)
            if fixtures:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.TESTING,
                        name="pytest_fixtures",
                        description=f"Uses pytest fixtures ({len(fixtures)} in this file)",
                        evidence=["@pytest.fixture"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

            # Parametrize
            parametrize = re.findall(r"@pytest\.mark\.parametrize", source)
            if parametrize:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.TESTING,
                        name="parametrized_tests",
                        description="Uses pytest.mark.parametrize for test parameterization",
                        evidence=["@pytest.mark.parametrize"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

        elif "import unittest" in source or "unittest.TestCase" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="test_framework",
                    description="Uses unittest as the test framework",
                    evidence=["import unittest"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Mock usage
        if "unittest.mock" in source or "from unittest.mock" in source:
            mock_style = "decorator" if "@patch" in source else "context manager"
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="mocking",
                    description=f"Uses unittest.mock ({mock_style} style)",
                    evidence=["from unittest.mock import patch"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Assert style
        if "assert " in source and "self.assert" not in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="assertion_style",
                    description="Uses plain assert statements (pytest style)",
                    evidence=["assert result == expected"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )
        elif "self.assert" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="assertion_style",
                    description="Uses self.assert* methods (unittest style)",
                    evidence=["self.assertEqual(...)"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        if "describe(" in source or "it(" in source or "test(" in source:
            framework = "jest"
            if "import { describe" in source and "vitest" in source:
                framework = "vitest"
            elif "mocha" in source.lower():
                framework = "mocha"
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="test_framework",
                    description=f"Uses {framework} for testing",
                    evidence=["describe('...', () => { test('...', ...) })"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "expect(" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="assertion_style",
                    description="Uses expect() for assertions",
                    evidence=["expect(result).toBe(expected)"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.GO:
        # Table-driven tests
        if (
            "tests := []struct" in source
            or "cases := []struct" in source
            or "tt := []struct" in source
        ):
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="table_driven_tests",
                    description="Uses table-driven test pattern",
                    evidence=["tests := []struct{ ... }{ ... }"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "testing.T" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="test_framework",
                    description="Uses Go standard testing package",
                    evidence=["func TestXxx(t *testing.T)"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "testify" in source.lower() or "assert." in source or "require." in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="assertion_library",
                    description="Uses testify for assertions",
                    evidence=["assert.Equal(t, expected, actual)"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.RUST:
        if "#[test]" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="test_framework",
                    description="Uses Rust built-in test framework (#[test])",
                    evidence=["#[test]\nfn test_something() { ... }"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "assert_eq!" in source or "assert!" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.TESTING,
                    name="assertion_style",
                    description="Uses assert! and assert_eq! macros",
                    evidence=["assert_eq!(result, expected)"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    # Test file naming pattern
    if is_test:
        patterns.append(
            CodePattern(
                category=PatternCategory.TESTING,
                name="test_file_naming",
                description=f"Test file naming: {fname}",
                evidence=[fname],
                confidence=Confidence.HIGH,
                language=lang,
                file_path=file_path,
            )
        )

    return patterns


# --- Import Style Extraction ---


def _extract_imports(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract import style patterns."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        # Absolute vs relative imports
        abs_imports = re.findall(r"^from\s+([a-zA-Z]\w*(?:\.\w+)*)\s+import", source, re.MULTILINE)
        rel_imports = re.findall(r"^from\s+(\.+\w*)\s+import", source, re.MULTILINE)

        if abs_imports and not rel_imports:
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="import_style",
                    description="Uses absolute imports exclusively",
                    evidence=[f"from {m} import ..." for m in abs_imports[:3]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )
        elif rel_imports:
            total = len(abs_imports) + len(rel_imports)
            rel_pct = len(rel_imports) / total if total > 0 else 0
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="import_style",
                    description=f"Uses relative imports ({rel_pct:.0%} of imports)",
                    evidence=[f"from {m} import ..." for m in rel_imports[:3]],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Import grouping (stdlib, third-party, local)
        import_lines = re.findall(r"^(?:import|from)\s+(\S+)", source, re.MULTILINE)
        if len(import_lines) >= 3:
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="import_volume",
                    description=f"File has {len(import_lines)} import statements",
                    evidence=[f"{len(import_lines)} imports in {file_path.name}"],
                    confidence=Confidence.LOW,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Check for __all__ exports
        if "__all__" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="export_control",
                    description="Uses __all__ to control public exports",
                    evidence=["__all__ = [...]"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # Named vs default imports
        named_imports = re.findall(r"import\s+\{[^}]+\}\s+from", source)
        if named_imports:
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="import_style",
                    description="Uses named imports (destructured)",
                    evidence=[named_imports[0].strip()[:80] if named_imports else ""],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Barrel files (index.ts re-exports)
        if file_path.stem == "index" and "export" in source:
            re_exports = re.findall(r"export\s+\{.*\}\s+from", source)
            if re_exports:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.IMPORTS,
                        name="barrel_files",
                        description="Uses barrel files (index.ts) for re-exports",
                        evidence=[re_exports[0].strip()[:80] if re_exports else ""],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

    elif lang == Language.GO:
        # Import grouping
        import_blocks = re.findall(r"import\s+\((.*?)\)", source, re.DOTALL)
        for block in import_blocks:
            lines = [ln.strip() for ln in block.strip().split("\n") if ln.strip()]
            has_blank_separator = "\n\n" in block or any(ln == "" for ln in block.split("\n"))
            if has_blank_separator and len(lines) > 2:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.IMPORTS,
                        name="import_grouping",
                        description="Go imports are grouped with blank line separators (stdlib / external / local)",
                        evidence=['import (\n\t"fmt"\n\n\t"github.com/..."\n)'],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )
                break

    return patterns


# --- Documentation Style Extraction ---


def _extract_documentation(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract documentation patterns."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        # Docstring style detection
        docstrings = re.findall(r'"""(.*?)"""', source, re.DOTALL)
        docstrings += re.findall(r"'''(.*?)'''", source, re.DOTALL)

        if docstrings:
            # Detect format: Google, NumPy, Sphinx
            google_style = sum(
                1 for d in docstrings if "Args:" in d or "Returns:" in d or "Raises:" in d
            )
            numpy_style = sum(1 for d in docstrings if "Parameters\n" in d or "----------" in d)
            sphinx_style = sum(1 for d in docstrings if ":param " in d or ":returns:" in d)

            if google_style > 0:
                style = "Google-style"
                evidence_sample = [
                    d[:100].strip() for d in docstrings if "Args:" in d or "Returns:" in d
                ][:2]
            elif numpy_style > 0:
                style = "NumPy-style"
                evidence_sample = [d[:100].strip() for d in docstrings if "Parameters" in d][:2]
            elif sphinx_style > 0:
                style = "Sphinx-style"
                evidence_sample = [d[:100].strip() for d in docstrings if ":param" in d][:2]
            else:
                style = "simple"
                evidence_sample = [d[:100].strip() for d in docstrings[:2]]

            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="docstring_style",
                    description=f"Uses {style} docstrings ({len(docstrings)} found)",
                    evidence=evidence_sample if evidence_sample else ["Docstrings present"],
                    confidence=Confidence.HIGH if len(docstrings) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Module-level docstring
        stripped = source.lstrip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="module_docstring",
                    description="Module-level docstring present",
                    evidence=[file_path.name],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # JSDoc comments
        jsdoc = re.findall(r"/\*\*(.*?)\*/", source, re.DOTALL)
        if jsdoc:
            has_param = any("@param" in d for d in jsdoc)
            has_returns = any("@returns" in d or "@return" in d for d in jsdoc)
            desc = "Uses JSDoc comments"
            if has_param:
                desc += " with @param tags"
            if has_returns:
                desc += " and @returns"
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="jsdoc",
                    description=f"{desc} ({len(jsdoc)} found)",
                    evidence=["/** ... @param ... @returns ... */"],
                    confidence=Confidence.HIGH if len(jsdoc) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Single-line comments
        comments = re.findall(r"^\s*//\s*(.+)$", source, re.MULTILINE)
        if len(comments) > 5:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="inline_comments",
                    description=f"Uses // inline comments ({len(comments)} found)",
                    evidence=comments[:3],
                    confidence=Confidence.LOW,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.GO:
        # Go doc comments (// FunctionName ...)
        doc_comments = re.findall(r"^//\s+([A-Z]\w+)\s+", source, re.MULTILINE)
        if doc_comments:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="go_doc_comments",
                    description=f"Uses Go doc comments (// FuncName ...) ({len(doc_comments)} found)",
                    evidence=[f"// {d} ..." for d in doc_comments[:3]],
                    confidence=Confidence.HIGH if len(doc_comments) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.RUST:
        # Rust doc comments (/// and //!)
        outer_docs = re.findall(r"^///\s*(.+)$", source, re.MULTILINE)
        inner_docs = re.findall(r"^//!\s*(.+)$", source, re.MULTILINE)
        if outer_docs or inner_docs:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="rust_doc_comments",
                    description=f"Uses /// doc comments ({len(outer_docs)} outer, {len(inner_docs)} inner)",
                    evidence=(
                        ["/// " + d for d in outer_docs[:2]] + ["//! " + d for d in inner_docs[:1]]
                    ),
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.JAVA:
        # Javadoc
        javadoc = re.findall(r"/\*\*(.*?)\*/", source, re.DOTALL)
        if javadoc:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="javadoc",
                    description=f"Uses Javadoc comments ({len(javadoc)} found)",
                    evidence=["/** ... @param ... @return ... */"],
                    confidence=Confidence.HIGH if len(javadoc) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    return patterns


# --- Code Style Extraction ---


def _extract_style(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract code style patterns."""
    patterns: list[CodePattern] = []

    # Line length analysis
    lines = source.split("\n")
    if lines:
        max_len = max(len(ln) for ln in lines)
        long_lines = sum(1 for ln in lines if len(ln) > 88)
        total_lines = len(lines)
        if total_lines > 10:
            if long_lines == 0:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="line_length",
                        description="All lines within 88 characters (Black default)",
                        evidence=[f"Max line: {max_len} chars in {file_path.name}"],
                        confidence=Confidence.MEDIUM,
                        language=lang,
                        file_path=file_path,
                    )
                )
            elif long_lines / total_lines < 0.05:
                long_120 = sum(1 for ln in lines if len(ln) > 120)
                if long_120 == 0:
                    patterns.append(
                        CodePattern(
                            category=PatternCategory.STYLE,
                            name="line_length",
                            description="Lines generally within 120 characters",
                            evidence=[f"Max line: {max_len} chars in {file_path.name}"],
                            confidence=Confidence.MEDIUM,
                            language=lang,
                            file_path=file_path,
                        )
                    )

    if lang == Language.PYTHON:
        # Quote style
        double_quotes = len(re.findall(r'(?<!=)"(?!=)[^"]*"', source))
        single_quotes = len(re.findall(r"(?<!=)'(?!=)[^']*'", source))
        if double_quotes + single_quotes > 5:
            if double_quotes > single_quotes * 2:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="quote_style",
                        description="Prefers double quotes",
                        evidence=[f"{double_quotes} double vs {single_quotes} single"],
                        confidence=Confidence.MEDIUM,
                        language=lang,
                        file_path=file_path,
                    )
                )
            elif single_quotes > double_quotes * 2:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="quote_style",
                        description="Prefers single quotes",
                        evidence=[f"{single_quotes} single vs {double_quotes} double"],
                        confidence=Confidence.MEDIUM,
                        language=lang,
                        file_path=file_path,
                    )
                )

        # Type hints
        type_hints = re.findall(r"def\s+\w+\([^)]*:\s*\w+", source)
        return_hints = re.findall(r"\)\s*->\s*\w+", source)
        if type_hints or return_hints:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="type_hints",
                    description=f"Uses type hints ({len(type_hints)} param annotations, {len(return_hints)} return annotations)",
                    evidence=["def func(x: int) -> str:"],
                    confidence=Confidence.HIGH
                    if (len(type_hints) + len(return_hints)) > 5
                    else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Trailing commas
        trailing_commas = len(re.findall(r",\s*[\]\)\}]\s*$", source, re.MULTILINE))
        if trailing_commas > 3:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="trailing_commas",
                    description="Uses trailing commas in collections and function args",
                    evidence=[f"{trailing_commas} trailing commas found"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # Semicolons
        lines_with_semi = sum(1 for ln in lines if ln.rstrip().endswith(";"))
        code_lines = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("//"))
        if code_lines > 10:
            semi_ratio = lines_with_semi / code_lines
            if semi_ratio > 0.3:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="semicolons",
                        description="Uses semicolons at end of statements",
                        evidence=[f"{semi_ratio:.0%} of code lines end with ;"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )
            elif semi_ratio < 0.1:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="semicolons",
                        description="Does not use semicolons (no-semi style)",
                        evidence=[f"Only {semi_ratio:.0%} of code lines end with ;"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

        # Quote style
        double_q = len(re.findall(r'"[^"]*"', source))
        single_q = len(re.findall(r"'[^']*'", source))
        total_q = double_q + single_q
        if total_q > 5:
            if single_q > double_q * 2:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="quote_style",
                        description="Prefers single quotes",
                        evidence=[f"{single_q} single vs {double_q} double"],
                        confidence=Confidence.MEDIUM,
                        language=lang,
                        file_path=file_path,
                    )
                )
            elif double_q > single_q * 2:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.STYLE,
                        name="quote_style",
                        description="Prefers double quotes",
                        evidence=[f"{double_q} double vs {single_q} single"],
                        confidence=Confidence.MEDIUM,
                        language=lang,
                        file_path=file_path,
                    )
                )

        # const vs let vs var
        const_count = len(re.findall(r"\bconst\b", source))
        let_count = len(re.findall(r"\blet\b", source))
        var_count = len(re.findall(r"\bvar\b", source))
        if const_count + let_count + var_count > 5 and var_count == 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="variable_declaration",
                    description=f"Uses const ({const_count}) and let ({let_count}), no var",
                    evidence=["const x = ...; let y = ...;"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    return patterns


# --- Logging Extraction ---


def _extract_logging(source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract logging and observability patterns."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        if "import logging" in source or "from logging" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses Python standard logging module",
                    evidence=["import logging"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

            # Logger instantiation pattern
            logger_init = re.findall(r"(\w+)\s*=\s*logging\.getLogger\(", source)
            if logger_init:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.LOGGING,
                        name="logger_init",
                        description=f"Logger initialized as: {logger_init[0]} = logging.getLogger(...)",
                        evidence=[f"{logger_init[0]} = logging.getLogger(...)"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

        if "import structlog" in source or "from structlog" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses structlog for structured logging",
                    evidence=["import structlog"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Log levels
        for level in ("debug", "info", "warning", "error", "critical"):
            calls = re.findall(rf"\.{level}\(", source)
            if calls:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.LOGGING,
                        name=f"log_level_{level}",
                        description=f"Uses log level: {level} ({len(calls)} calls)",
                        evidence=[f"logger.{level}(...)"],
                        confidence=Confidence.LOW,
                        language=lang,
                        file_path=file_path,
                    )
                )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        if "winston" in source.lower():
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses winston for logging",
                    evidence=["import winston"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )
        elif "pino" in source.lower():
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses pino for logging",
                    evidence=["import pino"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        console_logs = len(re.findall(r"console\.(log|warn|error|info|debug)\(", source))
        if console_logs > 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="console_logging",
                    description=f"Uses console.* for logging ({console_logs} calls)",
                    evidence=["console.log(...)"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.GO:
        if '"log"' in source or "log." in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses Go standard log package",
                    evidence=['import "log"'],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "zerolog" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses zerolog for structured logging",
                    evidence=["zerolog"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "logrus" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses logrus for structured logging",
                    evidence=["logrus"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        if "zap" in source and ("go.uber.org/zap" in source or "zap.Logger" in source):
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses zap for structured logging",
                    evidence=["go.uber.org/zap"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.RUST:
        if "use log::" in source or "use tracing::" in source:
            lib = "tracing" if "tracing" in source else "log"
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description=f"Uses {lib} crate for logging",
                    evidence=[f"use {lib}::*"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.JAVA:
        if "org.slf4j" in source or "LoggerFactory" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses SLF4J for logging",
                    evidence=["LoggerFactory.getLogger(...)"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )
        elif "java.util.logging" in source:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses java.util.logging",
                    evidence=["java.util.logging.Logger"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )
        elif "log4j" in source.lower():
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="logging_library",
                    description="Uses Log4j for logging",
                    evidence=["import org.apache.log4j"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    return patterns


# --- Architecture Pattern Extraction ---


def _extract_architecture(project_info: ProjectInfo) -> list[CodePattern]:
    """Extract architecture patterns from directory structure."""
    patterns: list[CodePattern] = []
    root = project_info.root_path

    # Collect all directory names relative to root
    dir_names: set[str] = set()
    top_dirs: list[str] = []

    try:
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                top_dirs.append(entry.name)
                dir_names.add(entry.name)
    except OSError:
        return patterns

    if top_dirs:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="top_level_dirs",
                description=f"Top-level directories: {', '.join(top_dirs[:10])}",
                evidence=[f"{d}/" for d in top_dirs[:10]],
                confidence=Confidence.HIGH,
            )
        )

    # Common architecture patterns
    # Layered: controllers/services/repositories or handlers/services/models
    layered_dirs = {"controllers", "services", "repositories", "handlers", "models", "views"}
    found_layers = layered_dirs & dir_names
    if len(found_layers) >= 2:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="layered_architecture",
                description=f"Layered architecture with: {', '.join(sorted(found_layers))}",
                evidence=[f"{d}/" for d in sorted(found_layers)],
                confidence=Confidence.HIGH,
            )
        )

    # Source directory patterns
    if "src" in dir_names:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="src_directory",
                description="Source code organized under src/ directory",
                evidence=["src/"],
                confidence=Confidence.HIGH,
            )
        )

    # Test directory
    test_dirs = {"tests", "test", "__tests__", "spec"}
    found_test_dirs = test_dirs & dir_names
    if found_test_dirs:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="test_directory",
                description=f"Tests organized in: {', '.join(sorted(found_test_dirs))}/",
                evidence=[f"{d}/" for d in sorted(found_test_dirs)],
                confidence=Confidence.HIGH,
            )
        )

    # Go-specific patterns
    go_dirs = {"cmd", "internal", "pkg"}
    found_go = go_dirs & dir_names
    if len(found_go) >= 2:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="go_project_layout",
                description=f"Standard Go project layout: {', '.join(sorted(found_go))}/",
                evidence=[f"{d}/" for d in sorted(found_go)],
                confidence=Confidence.HIGH,
            )
        )

    # Docs directory
    if "docs" in dir_names or "doc" in dir_names:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="documentation_dir",
                description="Has dedicated documentation directory",
                evidence=["docs/"],
                confidence=Confidence.MEDIUM,
            )
        )

    # Config/CI patterns
    if ".github" in dir_names:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name="github_actions",
                description="Uses GitHub Actions (has .github/ directory)",
                evidence=[".github/"],
                confidence=Confidence.HIGH,
            )
        )

    # Framework-specific patterns
    for fw in project_info.frameworks:
        patterns.append(
            CodePattern(
                category=PatternCategory.ARCHITECTURE,
                name=f"framework_{fw.name.lower().replace('.', '_')}",
                description=f"Uses {fw.name} framework ({fw.evidence})",
                evidence=[fw.evidence],
                confidence=Confidence.HIGH,
                language=fw.language,
            )
        )

    return patterns
