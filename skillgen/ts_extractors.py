"""Tree-sitter-powered pattern extractors.

Each extractor takes a pre-parsed root Node and produces CodePattern objects
identical to those from the regex extractors in analyzer.py.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from skillgen.analyzer import _classify_name
from skillgen.models import (
    CodePattern,
    Confidence,
    Language,
    PatternCategory,
)
from skillgen.ts_parser import (
    child_by_field,
    node_text,
    walk_tree,
    walk_tree_multi,
)

if TYPE_CHECKING:
    from tree_sitter import Node


def ts_extract_all(
    root: Node,
    source: str,
    lang: Language,
    file_path: Path,
) -> list[CodePattern]:
    """Run all tree-sitter extractors on a pre-parsed root node.

    The root node should come from ts_parser.parse_source(). The source
    string is needed for text-level analysis (line length, semicolons, etc.).
    """
    patterns: list[CodePattern] = []
    patterns.extend(ts_extract_naming(root, lang, file_path))
    patterns.extend(ts_extract_error_handling(root, lang, file_path))
    patterns.extend(ts_extract_testing(root, source, lang, file_path))
    patterns.extend(ts_extract_imports(root, lang, file_path))
    patterns.extend(ts_extract_documentation(root, lang, file_path))
    patterns.extend(ts_extract_style(root, source, lang, file_path))
    patterns.extend(ts_extract_logging(root, lang, file_path))
    return patterns


# ---------------------------------------------------------------------------
# Naming Convention Extraction
# ---------------------------------------------------------------------------


def _extract_func_names_from_tree(root: Node, lang: Language) -> list[str]:
    """Extract function/method names from the AST."""
    names: list[str] = []

    if lang == Language.PYTHON:
        for node in walk_tree(root, "function_definition"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        for node in walk_tree(root, "function_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        # Arrow functions assigned to const/let/var
        for node in walk_tree_multi(root, {"lexical_declaration", "variable_declaration"}):
            for decl in node.children:
                if decl.type == "variable_declarator":
                    val = child_by_field(decl, "value")
                    if val and val.type in ("arrow_function", "function"):
                        name_node = child_by_field(decl, "name")
                        if name_node:
                            names.append(node_text(name_node))
        # Method definitions in classes
        for node in walk_tree(root, "method_definition"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.JAVA:
        for node in walk_tree(root, "method_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.GO:
        for node in walk_tree(root, "function_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        for node in walk_tree(root, "method_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.RUST:
        for node in walk_tree(root, "function_item"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.CPP:
        for node in walk_tree(root, "function_definition"):
            declarator = child_by_field(node, "declarator")
            if declarator:
                name_node = child_by_field(declarator, "declarator")
                if name_node:
                    names.append(node_text(name_node))

    # Filter out special names
    names = [n for n in names if not n.startswith("__") and n not in ("main", "init")]
    return names


def _extract_class_names_from_tree(root: Node, lang: Language) -> list[str]:
    """Extract class/struct/type names from the AST."""
    names: list[str] = []

    if lang == Language.PYTHON:
        for node in walk_tree(root, "class_definition"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        for node in walk_tree(root, "class_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        # Also interfaces in TypeScript
        for node in walk_tree(root, "interface_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        # Type aliases
        for node in walk_tree(root, "type_alias_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.JAVA:
        for node in walk_tree(root, "class_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        for node in walk_tree(root, "interface_declaration"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.GO:
        for node in walk_tree(root, "type_declaration"):
            for child in node.children:
                if child.type == "type_spec":
                    name_node = child_by_field(child, "name")
                    type_node = child_by_field(child, "type")
                    if name_node and type_node and type_node.type == "struct_type":
                        names.append(node_text(name_node))

    elif lang == Language.RUST:
        for node in walk_tree(root, "struct_item"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        for node in walk_tree(root, "enum_item"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    elif lang == Language.CPP:
        for node in walk_tree(root, "class_specifier"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))
        for node in walk_tree(root, "struct_specifier"):
            name_node = child_by_field(node, "name")
            if name_node:
                names.append(node_text(name_node))

    return names


def ts_extract_naming(root: Node, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract naming convention patterns using tree-sitter."""
    patterns: list[CodePattern] = []
    func_names = _extract_func_names_from_tree(root, lang)
    class_names = _extract_class_names_from_tree(root, lang)

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
            break

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

    # BONUS: Detect decorators (tree-sitter advantage: accurate extraction)
    if lang == Language.PYTHON:
        decorators: list[str] = []
        for node in walk_tree(root, "decorator"):
            text = node_text(node).lstrip("@").split("(")[0].strip()
            if text and text not in decorators:
                decorators.append(text)
        if len(decorators) >= 2:
            patterns.append(
                CodePattern(
                    category=PatternCategory.NAMING,
                    name="decorator_usage",
                    description=f"Uses decorators: {', '.join(decorators[:5])}",
                    evidence=[f"@{d}" for d in decorators[:5]],
                    confidence=Confidence.HIGH if len(decorators) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    return patterns


# ---------------------------------------------------------------------------
# Error Handling Extraction
# ---------------------------------------------------------------------------


def ts_extract_error_handling(root: Node, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract error handling patterns using tree-sitter."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        except_types: list[str] = []
        for node in walk_tree(root, "except_clause"):
            for child in node.children:
                if child.type in ("identifier", "attribute"):
                    except_types.append(node_text(child))
                    break

        if except_types:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="exception_types",
                    description=f"Uses try/except with types: {', '.join(set(except_types[:5]))}",
                    evidence=[f"except {t}" for t in except_types[:5]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        for node in walk_tree(root, "class_definition"):
            name_node = child_by_field(node, "name")
            superclasses_node = child_by_field(node, "superclasses")
            if name_node and superclasses_node:
                super_text = node_text(superclasses_node)
                if "Exception" in super_text or "Error" in super_text:
                    class_name = node_text(name_node)
                    patterns.append(
                        CodePattern(
                            category=PatternCategory.ERROR_HANDLING,
                            name="custom_exceptions",
                            description=f"Defines custom exception: {class_name}",
                            evidence=[f"class {class_name}({super_text.strip('()')})"],
                            confidence=Confidence.HIGH,
                            language=lang,
                            file_path=file_path,
                        )
                    )

        raise_nodes = walk_tree(root, "raise_statement")
        raise_types: list[str] = []
        for node in raise_nodes:
            for child in node.children:
                if child.type in ("identifier", "call"):
                    text = node_text(child).split("(")[0]
                    raise_types.append(text)
                    break
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
        catch_clauses = walk_tree(root, "catch_clause")
        if catch_clauses:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="try_catch",
                    description="Uses try/catch blocks for error handling",
                    evidence=[f"catch (e) [{len(catch_clauses)} blocks]"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Custom error classes (class X extends Error)
        custom_errors: list[str] = []
        for node in walk_tree(root, "class_declaration"):
            for child in node.children:
                if child.type == "class_heritage" and "Error" in node_text(child):
                    name_node = child_by_field(node, "name")
                    if name_node:
                        custom_errors.append(node_text(name_node))
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
        # if err != nil pattern — tree-sitter gives us accurate if-statements
        err_checks = 0
        for node in walk_tree(root, "if_statement"):
            cond = child_by_field(node, "condition")
            if cond and "err" in node_text(cond) and "nil" in node_text(cond):
                err_checks += 1
        if err_checks:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="err_nil_check",
                    description=f"Uses 'if err != nil' pattern ({err_checks} occurrences)",
                    evidence=["if err != nil { ... }"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # fmt.Errorf wrapping
        errorf_count = 0
        has_wrap = False
        for node in walk_tree(root, "call_expression"):
            fn = child_by_field(node, "function")
            fn_text = node_text(fn)
            if fn_text == "fmt.Errorf":
                errorf_count += 1
                if "%w" in node_text(node):
                    has_wrap = True
        if errorf_count:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="error_wrapping",
                    description="Wraps errors with fmt.Errorf" + (" using %w" if has_wrap else ""),
                    evidence=[f"fmt.Errorf({errorf_count} calls)"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.RUST:
        # Result type usage — look for function return types containing Result
        result_count = 0
        for node in walk_tree(root, "function_item"):
            ret = child_by_field(node, "return_type")
            if ret and "Result" in node_text(ret):
                result_count += 1
        if result_count:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="result_type",
                    description="Uses Result<T, E> for error handling",
                    evidence=[f"{result_count} functions return Result"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # ? operator
        try_exprs = walk_tree(root, "try_expression")
        if try_exprs:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="question_mark_operator",
                    description=f"Uses ? operator for error propagation ({len(try_exprs)} occurrences)",
                    evidence=["Uses ? for early return on error"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # .unwrap() calls
        unwrap_calls = [
            n for n in walk_tree(root, "call_expression") if node_text(n).endswith(".unwrap()")
        ]
        if unwrap_calls:
            patterns.append(
                CodePattern(
                    category=PatternCategory.ERROR_HANDLING,
                    name="unwrap_usage",
                    description=f".unwrap() used {len(unwrap_calls)} times (consider expect() or ?)",
                    evidence=[".unwrap()"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.JAVA:
        # Catch clause types
        catch_types: list[str] = []
        for node in walk_tree(root, "catch_clause"):
            # The parameter is in catch_formal_parameter
            for child in node.children:
                if child.type == "catch_formal_parameter":
                    for sub in child.children:
                        if sub.type == "catch_type" or sub.type in (
                            "type_identifier",
                            "scoped_type_identifier",
                        ):
                            catch_types.append(node_text(sub))
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


# ---------------------------------------------------------------------------
# Testing Pattern Extraction
# ---------------------------------------------------------------------------


def ts_extract_testing(
    root: Node, source: str, lang: Language, file_path: Path
) -> list[CodePattern]:
    """Extract testing patterns using tree-sitter.

    Takes source text in addition to root node because test-file detection
    uses filename-based heuristics alongside AST analysis.
    """
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
        # Check for #[cfg(test)] attribute in AST
        for node in walk_tree(root, "attribute_item"):
            if "cfg(test)" in node_text(node) or node_text(node).strip("#[]") == "test":
                is_test = True
                break
        if not is_test:
            is_test = "#[test]" in source
    elif lang == Language.JAVA:
        is_test = "Test" in fname or any(
            "Test" in node_text(n) for n in walk_tree(root, "marker_annotation")
        )

    if not is_test:
        return patterns

    if lang == Language.PYTHON:
        # Count test functions accurately via AST
        test_funcs = [
            n
            for n in walk_tree(root, "function_definition")
            if node_text(child_by_field(n, "name")).startswith("test_")
        ]

        # Check for pytest decorators
        has_pytest_import = any(
            "pytest" in node_text(n) for n in walk_tree(root, "import_from_statement")
        ) or any("pytest" in node_text(n) for n in walk_tree(root, "import_statement"))

        fixture_count = 0
        parametrize_count = 0
        for node in walk_tree(root, "decorator"):
            text = node_text(node)
            if "pytest.fixture" in text:
                fixture_count += 1
            if "pytest.mark.parametrize" in text:
                parametrize_count += 1

        if has_pytest_import or fixture_count > 0 or parametrize_count > 0:
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
            if fixture_count > 0:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.TESTING,
                        name="pytest_fixtures",
                        description=f"Uses pytest fixtures ({fixture_count} in this file)",
                        evidence=["@pytest.fixture"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )
            if parametrize_count > 0:
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
        else:
            # Check for unittest
            has_unittest = any(
                "unittest" in node_text(n)
                for n in walk_tree_multi(root, {"import_statement", "import_from_statement"})
            )
            if has_unittest:
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

        # Assertion style — check for assert statements vs self.assert* calls
        assert_stmts = walk_tree(root, "assert_statement")
        self_asserts = [
            n for n in walk_tree(root, "call") if node_text(n).startswith("self.assert")
        ]
        if assert_stmts and not self_asserts:
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
        elif self_asserts:
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
        # Detect describe/it/test calls via AST
        call_names: list[str] = []
        for node in walk_tree(root, "call_expression"):
            fn = child_by_field(node, "function")
            if fn:
                call_names.append(node_text(fn))

        has_describe = "describe" in call_names
        has_test = "test" in call_names or "it" in call_names

        if has_describe or has_test:
            framework = "jest"
            # Check imports for vitest/mocha
            for node in walk_tree_multi(root, {"import_statement", "import_from_statement"}):
                text = node_text(node)
                if "vitest" in text:
                    framework = "vitest"
                elif "mocha" in text:
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

        if "expect" in call_names:
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
        # Detect test functions: func TestXxx(t *testing.T)
        test_funcs = [
            n
            for n in walk_tree(root, "function_declaration")
            if node_text(child_by_field(n, "name")).startswith("Test")
        ]
        if test_funcs:
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

        # Table-driven tests — look for composite_literal of slice of struct
        for node in walk_tree(root, "short_var_declaration"):
            text = node_text(node)
            if "[]struct" in text:
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
                break

        # Testify usage
        for node in walk_tree_multi(root, {"import_statement", "import_declaration"}):
            text = node_text(node)
            if "testify" in text or "assert" in text:
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
                break

    elif lang == Language.RUST:
        # Detect #[test] attributes
        test_attrs = [
            n for n in walk_tree(root, "attribute_item") if node_text(n).strip("#[]") == "test"
        ]
        if test_attrs:
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

        # assert! and assert_eq! macros
        macro_calls = walk_tree(root, "macro_invocation")
        assert_macros = [
            n for n in macro_calls if node_text(n).startswith(("assert!", "assert_eq!"))
        ]
        if assert_macros:
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

    # Test file naming
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


# ---------------------------------------------------------------------------
# Import Style Extraction
# ---------------------------------------------------------------------------


def ts_extract_imports(root: Node, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract import style patterns using tree-sitter."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        abs_imports: list[str] = []
        rel_imports: list[str] = []

        for node in walk_tree(root, "import_from_statement"):
            module_node = child_by_field(node, "module_name")
            if module_node:
                text = node_text(module_node)
                if text.startswith("."):
                    rel_imports.append(text)
                else:
                    abs_imports.append(text)

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

        # Import count
        all_imports = walk_tree_multi(root, {"import_statement", "import_from_statement"})
        if len(all_imports) >= 3:
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="import_volume",
                    description=f"File has {len(all_imports)} import statements",
                    evidence=[f"{len(all_imports)} imports in {file_path.name}"],
                    confidence=Confidence.LOW,
                    language=lang,
                    file_path=file_path,
                )
            )

        # __all__ — look for assignment to __all__
        for node in walk_tree_multi(root, {"expression_statement", "assignment"}):
            if "__all__" in node_text(node):
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
                break

        # BONUS: TYPE_CHECKING guard (tree-sitter can detect this accurately)
        for node in walk_tree(root, "if_statement"):
            cond = child_by_field(node, "condition")
            if cond and "TYPE_CHECKING" in node_text(cond):
                patterns.append(
                    CodePattern(
                        category=PatternCategory.IMPORTS,
                        name="type_checking_guard",
                        description="Uses TYPE_CHECKING guard for import-time type-only imports",
                        evidence=["if TYPE_CHECKING:\n    from ... import ..."],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )
                break

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # Named imports
        named_imports = walk_tree(root, "import_statement")
        named_destructured = [
            n for n in named_imports if any(c.type == "import_clause" for c in n.children)
        ]
        if named_destructured:
            first = node_text(named_destructured[0])[:80]
            patterns.append(
                CodePattern(
                    category=PatternCategory.IMPORTS,
                    name="import_style",
                    description="Uses named imports (destructured)",
                    evidence=[first] if first else [],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Barrel files
        if file_path.stem == "index":
            export_stmts = walk_tree(root, "export_statement")
            re_exports = [n for n in export_stmts if "from" in node_text(n)]
            if re_exports:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.IMPORTS,
                        name="barrel_files",
                        description="Uses barrel files (index.ts) for re-exports",
                        evidence=[node_text(re_exports[0])[:80]],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

    elif lang == Language.GO:
        # Import grouping — check for blank lines in import_spec_list
        for node in walk_tree(root, "import_declaration"):
            text = node_text(node)
            specs = [c for c in node.children if c.type == "import_spec_list"]
            if specs:
                spec_text = node_text(specs[0])
                if "\n\n" in spec_text:
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


# ---------------------------------------------------------------------------
# Documentation Style Extraction
# ---------------------------------------------------------------------------


def ts_extract_documentation(root: Node, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract documentation patterns using tree-sitter."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        # Find actual docstrings (first expression_statement in function/class body)
        docstrings: list[str] = []
        func_count = 0
        for node in walk_tree_multi(root, {"function_definition", "class_definition"}):
            func_count += 1
            body = child_by_field(node, "body")
            if body and body.children:
                first_stmt = body.children[0]
                if first_stmt.type == "expression_statement":
                    expr = first_stmt.children[0] if first_stmt.children else None
                    if expr and expr.type == "string":
                        docstrings.append(node_text(expr))

        if docstrings:
            # Detect docstring format
            google_style = sum(
                1 for d in docstrings if "Args:" in d or "Returns:" in d or "Raises:" in d
            )
            numpy_style = sum(1 for d in docstrings if "Parameters\n" in d or "----------" in d)
            sphinx_style = sum(1 for d in docstrings if ":param " in d or ":returns:" in d)

            if google_style > 0:
                style = "Google-style"
            elif numpy_style > 0:
                style = "NumPy-style"
            elif sphinx_style > 0:
                style = "Sphinx-style"
            else:
                style = "simple"

            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="docstring_style",
                    description=f"Uses {style} docstrings ({len(docstrings)} found)",
                    evidence=docstrings[:2],
                    confidence=Confidence.HIGH if len(docstrings) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

            # Docstring coverage
            if func_count > 0:
                coverage = len(docstrings) / func_count
                if coverage > 0.5:
                    patterns.append(
                        CodePattern(
                            category=PatternCategory.DOCUMENTATION,
                            name="docstring_coverage",
                            description=f"Docstring coverage: {coverage:.0%} of functions/classes",
                            evidence=[f"{len(docstrings)}/{func_count} have docstrings"],
                            confidence=Confidence.MEDIUM,
                            language=lang,
                            file_path=file_path,
                        )
                    )

        # Module-level docstring
        if root.children:
            first = root.children[0]
            if first.type == "expression_statement" and first.children:
                expr = first.children[0]
                if expr.type == "string":
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
        # JSDoc comments are represented as "comment" nodes
        comments = walk_tree(root, "comment")
        jsdoc_comments = [c for c in comments if node_text(c).startswith("/**")]
        if jsdoc_comments:
            has_param = any("@param" in node_text(c) for c in jsdoc_comments)
            has_returns = any(
                "@returns" in node_text(c) or "@return" in node_text(c) for c in jsdoc_comments
            )
            desc = "Uses JSDoc comments"
            if has_param:
                desc += " with @param tags"
            if has_returns:
                desc += " and @returns"
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="jsdoc",
                    description=f"{desc} ({len(jsdoc_comments)} found)",
                    evidence=["/** ... @param ... @returns ... */"],
                    confidence=Confidence.HIGH if len(jsdoc_comments) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Single-line comments
        inline_comments = [c for c in comments if node_text(c).startswith("//")]
        if len(inline_comments) > 5:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="inline_comments",
                    description=f"Uses // inline comments ({len(inline_comments)} found)",
                    evidence=[node_text(c) for c in inline_comments[:3]],
                    confidence=Confidence.LOW,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.GO:
        # Go doc comments (// FuncName ...)
        comments = walk_tree(root, "comment")
        doc_comments = [
            c for c in comments if node_text(c).startswith("//") and len(node_text(c)) > 3
        ]
        # Filter to those that look like Go doc comments (start with uppercase word after //)
        go_docs = [c for c in doc_comments if len(node_text(c)) > 4 and node_text(c)[3:4].isupper()]
        if go_docs:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="go_doc_comments",
                    description=f"Uses Go doc comments (// FuncName ...) ({len(go_docs)} found)",
                    evidence=[node_text(c) for c in go_docs[:3]],
                    confidence=Confidence.HIGH if len(go_docs) >= 3 else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.RUST:
        comments = walk_tree_multi(root, {"line_comment", "doc_comment"})
        outer_docs = [c for c in comments if node_text(c).startswith("///")]
        inner_docs = [c for c in comments if node_text(c).startswith("//!")]
        if outer_docs or inner_docs:
            patterns.append(
                CodePattern(
                    category=PatternCategory.DOCUMENTATION,
                    name="rust_doc_comments",
                    description=f"Uses /// doc comments ({len(outer_docs)} outer, {len(inner_docs)} inner)",
                    evidence=[node_text(c) for c in outer_docs[:2]]
                    + [node_text(c) for c in inner_docs[:1]],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.JAVA:
        comments = walk_tree_multi(root, {"block_comment", "line_comment"})
        javadoc = [c for c in comments if node_text(c).startswith("/**")]
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


# ---------------------------------------------------------------------------
# Code Style Extraction
# ---------------------------------------------------------------------------


def ts_extract_style(root: Node, source: str, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract code style patterns using tree-sitter.

    Takes source text for line-length and semicolon analysis.
    """
    patterns: list[CodePattern] = []

    # Line length analysis (same as regex — this is text-level, not AST)
    lines = source.split("\n")
    if len(lines) > 10:
        max_len = max(len(ln) for ln in lines)
        long_88 = sum(1 for ln in lines if len(ln) > 88)
        long_120 = sum(1 for ln in lines if len(ln) > 120)
        total_lines = len(lines)

        if long_88 == 0:
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
        elif long_88 / total_lines < 0.05 and long_120 == 0:
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
        # Type annotation detection (tree-sitter advantage: accurate count)
        param_annotations = 0
        return_annotations = 0
        for node in walk_tree(root, "function_definition"):
            params = child_by_field(node, "parameters")
            if params:
                for param in params.children:
                    if param.type in ("typed_parameter", "typed_default_parameter"):
                        param_annotations += 1
            ret = child_by_field(node, "return_type")
            if ret:
                return_annotations += 1

        if param_annotations > 0 or return_annotations > 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="type_hints",
                    description=f"Uses type hints ({param_annotations} param annotations, {return_annotations} return annotations)",
                    evidence=["def func(x: int) -> str:"],
                    confidence=Confidence.HIGH
                    if (param_annotations + return_annotations) > 5
                    else Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Quote style
        strings = walk_tree(root, "string")
        double_q = sum(1 for s in strings if node_text(s).startswith('"'))
        single_q = sum(1 for s in strings if node_text(s).startswith("'"))
        if double_q + single_q > 5:
            if double_q > single_q * 2:
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
            elif single_q > double_q * 2:
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

        # Trailing commas (check tuple, list, dict, argument_list, parameter nodes)
        trailing_comma_count = 0
        for node in walk_tree_multi(
            root, {"tuple", "list", "dictionary", "argument_list", "parameters"}
        ):
            children = [c for c in node.children if c.type not in ("(", ")", "[", "]", "{", "}")]
            if children and children[-1].type == ",":
                trailing_comma_count += 1
        if trailing_comma_count > 3:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="trailing_commas",
                    description="Uses trailing commas in collections and function args",
                    evidence=[f"{trailing_comma_count} trailing commas found"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # Semicolons — count expression_statements ending with ";"
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

        # Quote style from actual string nodes
        strings = walk_tree(root, "string")
        double_q = sum(1 for s in strings if node_text(s).startswith('"'))
        single_q = sum(1 for s in strings if node_text(s).startswith("'"))
        # Also check template strings
        template_strings = walk_tree(root, "template_string")
        if double_q + single_q > 5:
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

        # const vs let vs var (accurate: counts declarations, not occurrences in strings)
        const_decls = len(walk_tree(root, "lexical_declaration"))
        var_decls = len(walk_tree(root, "variable_declaration"))
        # lexical_declaration covers both const and let
        if const_decls > 5 and var_decls == 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="variable_declaration",
                    description=f"Uses const/let declarations ({const_decls}), no var",
                    evidence=["const x = ...; let y = ...;"],
                    confidence=Confidence.HIGH,
                    language=lang,
                    file_path=file_path,
                )
            )

        # Template literals usage
        if template_strings and len(template_strings) >= 3:
            patterns.append(
                CodePattern(
                    category=PatternCategory.STYLE,
                    name="template_literals",
                    description=f"Uses template literals ({len(template_strings)} found)",
                    evidence=["`Hello ${name}`"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    return patterns


# ---------------------------------------------------------------------------
# Logging Extraction
# ---------------------------------------------------------------------------


def ts_extract_logging(root: Node, lang: Language, file_path: Path) -> list[CodePattern]:
    """Extract logging patterns using tree-sitter."""
    patterns: list[CodePattern] = []

    if lang == Language.PYTHON:
        # Check imports for logging/structlog
        has_logging = False
        has_structlog = False
        for node in walk_tree_multi(root, {"import_statement", "import_from_statement"}):
            text = node_text(node)
            if "logging" in text and "structlog" not in text:
                has_logging = True
            if "structlog" in text:
                has_structlog = True

        if has_logging:
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
            # Logger init pattern
            for node in walk_tree(root, "assignment"):
                text = node_text(node)
                if "logging.getLogger" in text:
                    var_name = text.split("=")[0].strip()
                    patterns.append(
                        CodePattern(
                            category=PatternCategory.LOGGING,
                            name="logger_init",
                            description=f"Logger initialized as: {var_name} = logging.getLogger(...)",
                            evidence=[f"{var_name} = logging.getLogger(...)"],
                            confidence=Confidence.HIGH,
                            language=lang,
                            file_path=file_path,
                        )
                    )
                    break

        if has_structlog:
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

        # Log level usage — walk "call" nodes once, classify by attribute name
        log_levels = {"debug", "info", "warning", "error", "critical"}
        level_counts: dict[str, int] = {}
        for node in walk_tree(root, "call"):
            fn = child_by_field(node, "function")
            if fn and fn.type == "attribute":
                attr = child_by_field(fn, "attribute")
                if attr:
                    attr_name = node_text(attr)
                    if attr_name in log_levels:
                        level_counts[attr_name] = level_counts.get(attr_name, 0) + 1
        for level, count in level_counts.items():
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name=f"log_level_{level}",
                    description=f"Uses log level: {level} ({count} calls)",
                    evidence=[f"logger.{level}(...)"],
                    confidence=Confidence.LOW,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        # Check for logging libraries in imports
        for node in walk_tree_multi(root, {"import_statement", "import_from_statement"}):
            text = node_text(node).lower()
            if "winston" in text:
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
            elif "pino" in text:
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

        # console.log/warn/error calls
        console_count = 0
        for node in walk_tree(root, "call_expression"):
            fn = child_by_field(node, "function")
            if fn:
                fn_text = node_text(fn)
                if fn_text.startswith("console."):
                    console_count += 1
        if console_count > 0:
            patterns.append(
                CodePattern(
                    category=PatternCategory.LOGGING,
                    name="console_logging",
                    description=f"Uses console.* for logging ({console_count} calls)",
                    evidence=["console.log(...)"],
                    confidence=Confidence.MEDIUM,
                    language=lang,
                    file_path=file_path,
                )
            )

    elif lang == Language.GO:
        # Check imports for logging packages
        for node in walk_tree(root, "import_declaration"):
            text = node_text(node)
            if '"log"' in text:
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
            if "zerolog" in text:
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
            if "logrus" in text:
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
            if "zap" in text:
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
        # Check for use log:: or use tracing::
        for node in walk_tree(root, "use_declaration"):
            text = node_text(node)
            if "tracing" in text:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.LOGGING,
                        name="logging_library",
                        description="Uses tracing crate for logging",
                        evidence=["use tracing::*"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )
            elif "log" in text:
                patterns.append(
                    CodePattern(
                        category=PatternCategory.LOGGING,
                        name="logging_library",
                        description="Uses log crate for logging",
                        evidence=["use log::*"],
                        confidence=Confidence.HIGH,
                        language=lang,
                        file_path=file_path,
                    )
                )

    elif lang == Language.JAVA:
        # Check imports for logging frameworks
        for node in walk_tree(root, "import_declaration"):
            text = node_text(node)
            if "slf4j" in text or "LoggerFactory" in text:
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
            elif "java.util.logging" in text:
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
            elif "log4j" in text:
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
