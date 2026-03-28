"""Tests for tree-sitter-powered pattern extractors.

All tests are skipped if tree-sitter is not installed, ensuring
CI passes in both configurations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillgen.models import (
    Confidence,
    Language,
    PatternCategory,
)
from skillgen.ts_parser import TREE_SITTER_AVAILABLE

pytestmark = pytest.mark.skipif(
    not TREE_SITTER_AVAILABLE,
    reason="tree-sitter not installed",
)


# Lazy import to avoid ImportError when tree-sitter is missing.
if TREE_SITTER_AVAILABLE:
    from skillgen.ts_extractors import (
        ts_extract_documentation,
        ts_extract_error_handling,
        ts_extract_imports,
        ts_extract_logging,
        ts_extract_naming,
        ts_extract_style,
        ts_extract_testing,
    )
    from skillgen.ts_parser import parse_source


FAKE_PATH = Path("test_file.py")


def _parse(source: str, lang: Language, path: Path = FAKE_PATH) -> object:
    """Parse source and return root node. Asserts parse succeeds."""
    root = parse_source(source, lang, path)
    assert root is not None, f"tree-sitter failed to parse {lang.value} source"
    return root


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


class TestTsNamingExtraction:
    def test_python_snake_case_functions(self) -> None:
        source = "def get_user():\n    pass\n\ndef set_name():\n    pass\n"
        patterns = ts_extract_naming(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        names = [p.name for p in patterns]
        assert "function_naming" in names
        func_pat = next(p for p in patterns if p.name == "function_naming")
        assert "snake_case" in func_pat.description

    def test_python_class_pascal_case(self) -> None:
        source = "class MyService:\n    pass\n\nclass UserHandler:\n    pass\n"
        patterns = ts_extract_naming(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        class_pat = [p for p in patterns if p.name == "class_naming"]
        assert class_pat
        assert "PascalCase" in class_pat[0].description

    def test_python_decorators_detected(self) -> None:
        source = (
            "import functools\n"
            "@functools.lru_cache\n"
            "def cached():\n    pass\n\n"
            "@staticmethod\n"
            "def static_fn():\n    pass\n\n"
            "@property\n"
            "def prop(self):\n    pass\n"
        )
        patterns = ts_extract_naming(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        dec_pat = [p for p in patterns if p.name == "decorator_usage"]
        assert dec_pat
        assert any("@" in e for e in dec_pat[0].evidence)

    def test_typescript_camel_case_functions(self) -> None:
        source = "function getUserById(id: string) { }\nfunction setName(n: string) { }\n"
        patterns = ts_extract_naming(
            _parse(source, Language.TYPESCRIPT, Path("test.ts")),
            Language.TYPESCRIPT,
            Path("test.ts"),
        )
        func_pat = [p for p in patterns if p.name == "function_naming"]
        assert func_pat
        assert "camelCase" in func_pat[0].description

    def test_go_functions_and_structs(self) -> None:
        source = (
            "package main\n"
            "type UserService struct{}\n"
            "func handleRequest() {}\n"
            "func (s *UserService) GetUser() {}\n"
        )
        patterns = ts_extract_naming(
            _parse(source, Language.GO, Path("main.go")), Language.GO, Path("main.go")
        )
        names = {p.name for p in patterns}
        assert "function_naming" in names
        assert "class_naming" in names

    def test_rust_functions_and_structs(self) -> None:
        source = "fn calculate_total() {}\nstruct UserConfig {}\nenum Status {}\n"
        patterns = ts_extract_naming(
            _parse(source, Language.RUST, Path("lib.rs")), Language.RUST, Path("lib.rs")
        )
        names = {p.name for p in patterns}
        assert "function_naming" in names
        assert "class_naming" in names

    def test_java_methods_and_classes(self) -> None:
        source = (
            "public class UserService {\n"
            "    public void getUser() {}\n"
            "    public void setName() {}\n"
            "}\n"
        )
        patterns = ts_extract_naming(
            _parse(source, Language.JAVA, Path("UserService.java")),
            Language.JAVA,
            Path("UserService.java"),
        )
        names = {p.name for p in patterns}
        assert "function_naming" in names
        assert "class_naming" in names

    def test_filters_dunder_methods(self) -> None:
        source = "def __init__(self):\n    pass\ndef __repr__(self):\n    pass\n"
        patterns = ts_extract_naming(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        func_pat = [p for p in patterns if p.name == "function_naming"]
        assert not func_pat  # dunder methods should be filtered


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestTsErrorHandling:
    def test_python_except_types(self) -> None:
        source = "try:\n    x = 1\nexcept ValueError:\n    pass\nexcept OSError:\n    pass\n"
        patterns = ts_extract_error_handling(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        exc_pat = [p for p in patterns if p.name == "exception_types"]
        assert exc_pat
        assert "ValueError" in exc_pat[0].description

    def test_python_custom_exception(self) -> None:
        source = "class AppError(Exception):\n    pass\n"
        patterns = ts_extract_error_handling(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        custom = [p for p in patterns if p.name == "custom_exceptions"]
        assert custom
        assert "AppError" in custom[0].description

    def test_python_raise_statement(self) -> None:
        source = "def f():\n    raise ValueError('bad')\n    raise TypeError\n"
        patterns = ts_extract_error_handling(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        raise_pat = [p for p in patterns if p.name == "raise_style"]
        assert raise_pat

    def test_go_err_nil_check(self) -> None:
        source = (
            "package main\n"
            "func foo() error {\n"
            "    err := doSomething()\n"
            "    if err != nil {\n"
            "        return err\n"
            "    }\n"
            "    return nil\n"
            "}\n"
        )
        patterns = ts_extract_error_handling(
            _parse(source, Language.GO, Path("main.go")), Language.GO, Path("main.go")
        )
        err_pat = [p for p in patterns if p.name == "err_nil_check"]
        assert err_pat

    def test_rust_result_and_question_mark(self) -> None:
        source = (
            "fn read_file(path: &str) -> Result<String, io::Error> {\n"
            "    let content = std::fs::read_to_string(path)?;\n"
            "    Ok(content)\n"
            "}\n"
        )
        patterns = ts_extract_error_handling(
            _parse(source, Language.RUST, Path("lib.rs")), Language.RUST, Path("lib.rs")
        )
        names = {p.name for p in patterns}
        assert "result_type" in names

    def test_js_try_catch(self) -> None:
        source = "try {\n  doStuff();\n} catch (e) {\n  console.error(e);\n}\n"
        patterns = ts_extract_error_handling(
            _parse(source, Language.JAVASCRIPT, Path("app.js")), Language.JAVASCRIPT, Path("app.js")
        )
        catch_pat = [p for p in patterns if p.name == "try_catch"]
        assert catch_pat


# ---------------------------------------------------------------------------
# Testing Patterns
# ---------------------------------------------------------------------------


class TestTsTestingPatterns:
    def test_pytest_detection(self) -> None:
        source = "import pytest\n\ndef test_something():\n    assert True\n"
        patterns = ts_extract_testing(
            _parse(source, Language.PYTHON, Path("test_main.py")),
            source,
            Language.PYTHON,
            Path("test_main.py"),
        )
        names = {p.name for p in patterns}
        assert "test_framework" in names
        fw = next(p for p in patterns if p.name == "test_framework")
        assert "pytest" in fw.description

    def test_pytest_fixture(self) -> None:
        source = "import pytest\n\n@pytest.fixture\ndef my_fixture():\n    return 42\n\ndef test_it(my_fixture):\n    assert my_fixture == 42\n"
        patterns = ts_extract_testing(
            _parse(source, Language.PYTHON, Path("test_fixtures.py")),
            source,
            Language.PYTHON,
            Path("test_fixtures.py"),
        )
        names = {p.name for p in patterns}
        assert "pytest_fixtures" in names

    def test_go_table_driven(self) -> None:
        source = (
            "package main\n"
            'import "testing"\n'
            "func TestAdd(t *testing.T) {\n"
            "    tests := []struct{\n"
            "        a, b, want int\n"
            "    }{{1,2,3},{0,0,0}}\n"
            "    for _, tt := range tests {\n"
            "        got := Add(tt.a, tt.b)\n"
            '        if got != tt.want { t.Errorf("bad") }\n'
            "    }\n"
            "}\n"
        )
        patterns = ts_extract_testing(
            _parse(source, Language.GO, Path("add_test.go")),
            source,
            Language.GO,
            Path("add_test.go"),
        )
        names = {p.name for p in patterns}
        assert "test_framework" in names
        assert "table_driven_tests" in names

    def test_jest_detection(self) -> None:
        source = "describe('math', () => {\n  test('adds', () => {\n    expect(1+1).toBe(2);\n  });\n});\n"
        patterns = ts_extract_testing(
            _parse(source, Language.JAVASCRIPT, Path("math.test.js")),
            source,
            Language.JAVASCRIPT,
            Path("math.test.js"),
        )
        names = {p.name for p in patterns}
        assert "test_framework" in names
        assert "assertion_style" in names

    def test_non_test_file_returns_empty(self) -> None:
        source = "def helper():\n    return 42\n"
        patterns = ts_extract_testing(
            _parse(source, Language.PYTHON, Path("utils.py")),
            source,
            Language.PYTHON,
            Path("utils.py"),
        )
        assert patterns == []


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


class TestTsImports:
    def test_python_absolute_imports(self) -> None:
        source = "from os.path import join\nfrom pathlib import Path\n"
        patterns = ts_extract_imports(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        imp_pat = [p for p in patterns if p.name == "import_style"]
        assert imp_pat
        assert "absolute" in imp_pat[0].description

    def test_python_relative_imports(self) -> None:
        source = "from .models import User\nfrom ..utils import helper\nfrom os import path\n"
        patterns = ts_extract_imports(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        imp_pat = [p for p in patterns if p.name == "import_style"]
        assert imp_pat
        assert "relative" in imp_pat[0].description.lower()

    def test_python_type_checking_guard(self) -> None:
        source = (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from pathlib import Path\n"
        )
        patterns = ts_extract_imports(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        tc_pat = [p for p in patterns if p.name == "type_checking_guard"]
        assert tc_pat

    def test_go_import_grouping(self) -> None:
        source = 'package main\n\nimport (\n\t"fmt"\n\t"os"\n\n\t"github.com/pkg/errors"\n)\n'
        patterns = ts_extract_imports(
            _parse(source, Language.GO, Path("main.go")), Language.GO, Path("main.go")
        )
        grp_pat = [p for p in patterns if p.name == "import_grouping"]
        assert grp_pat


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


class TestTsDocumentation:
    def test_python_google_style_docstrings(self) -> None:
        source = (
            '"""Module doc."""\n\n'
            'def foo():\n    """Do foo.\n\n    Args:\n        x: value\n    """\n    pass\n\n'
            'def bar():\n    """Do bar.\n\n    Returns:\n        int\n    """\n    pass\n'
        )
        patterns = ts_extract_documentation(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        names = {p.name for p in patterns}
        assert "docstring_style" in names
        assert "module_docstring" in names
        ds = next(p for p in patterns if p.name == "docstring_style")
        assert "Google-style" in ds.description

    def test_python_docstring_coverage(self) -> None:
        source = (
            'def a():\n    """Doc."""\n    pass\n\n'
            'def b():\n    """Doc."""\n    pass\n\n'
            'class C:\n    """Doc."""\n    pass\n'
        )
        patterns = ts_extract_documentation(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        cov = [p for p in patterns if p.name == "docstring_coverage"]
        assert cov
        assert "100%" in cov[0].description

    def test_jsdoc_detection(self) -> None:
        source = (
            "/**\n * Gets user by ID.\n * @param {string} id\n * @returns {User}\n */\n"
            "function getUser(id) { }\n"
        )
        patterns = ts_extract_documentation(
            _parse(source, Language.JAVASCRIPT, Path("api.js")), Language.JAVASCRIPT, Path("api.js")
        )
        jsdoc = [p for p in patterns if p.name == "jsdoc"]
        assert jsdoc
        assert "@param" in jsdoc[0].description


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------


class TestTsStyle:
    def test_python_type_hints(self) -> None:
        source = "def greet(name: str, count: int) -> str:\n    return name * count\n"
        patterns = ts_extract_style(
            _parse(source, Language.PYTHON, FAKE_PATH), source, Language.PYTHON, FAKE_PATH
        )
        th = [p for p in patterns if p.name == "type_hints"]
        assert th
        assert "2 param" in th[0].description
        assert "1 return" in th[0].description

    def test_python_quote_style(self) -> None:
        source = 'x = "hello"\ny = "world"\nz = "test"\na = "foo"\nb = "bar"\nc = "baz"\n'
        patterns = ts_extract_style(
            _parse(source, Language.PYTHON, FAKE_PATH), source, Language.PYTHON, FAKE_PATH
        )
        q = [p for p in patterns if p.name == "quote_style"]
        assert q
        assert "double" in q[0].description

    def test_js_semicolons(self) -> None:
        source = "\n".join(
            [
                "const x = 1;",
                "const y = 2;",
                "function foo() {",
                "  return x + y;",
                "}",
                "const z = foo();",
                "console.log(z);",
                "const a = 1;",
                "const b = 2;",
                "const c = 3;",
                "const d = 4;",
                "const e = 5;",
            ]
        )
        patterns = ts_extract_style(
            _parse(source, Language.JAVASCRIPT, Path("app.js")),
            source,
            Language.JAVASCRIPT,
            Path("app.js"),
        )
        semi = [p for p in patterns if p.name == "semicolons"]
        assert semi
        assert "Uses semicolons" in semi[0].description

    def test_line_length(self) -> None:
        source = "\n".join(["x = 1"] * 20)
        patterns = ts_extract_style(
            _parse(source, Language.PYTHON, FAKE_PATH), source, Language.PYTHON, FAKE_PATH
        )
        ll = [p for p in patterns if p.name == "line_length"]
        assert ll
        assert "88" in ll[0].description


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestTsLogging:
    def test_python_standard_logging(self) -> None:
        source = "import logging\n\nlogger = logging.getLogger(__name__)\nlogger.info('hello')\n"
        patterns = ts_extract_logging(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        names = {p.name for p in patterns}
        assert "logging_library" in names
        assert "logger_init" in names

    def test_python_structlog(self) -> None:
        source = "import structlog\n\nlog = structlog.get_logger()\n"
        patterns = ts_extract_logging(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        lib = [p for p in patterns if p.name == "logging_library"]
        assert lib
        assert "structlog" in lib[0].description

    def test_js_console_logging(self) -> None:
        source = "console.log('debug');\nconsole.error('fail');\n"
        patterns = ts_extract_logging(
            _parse(source, Language.JAVASCRIPT, Path("app.js")), Language.JAVASCRIPT, Path("app.js")
        )
        cl = [p for p in patterns if p.name == "console_logging"]
        assert cl
        assert "2 calls" in cl[0].description


# ---------------------------------------------------------------------------
# Integration: tree-sitter vs regex produce compatible output
# ---------------------------------------------------------------------------


class TestCompatibility:
    """Verify tree-sitter extractors produce CodePattern objects with
    the same names/categories as the regex extractors."""

    def test_pattern_categories_are_valid(self) -> None:
        source = (
            "import logging\n\nlogger = logging.getLogger(__name__)\n\n"
            "class MyError(Exception):\n    pass\n\n"
            "def get_user(name: str) -> str:\n"
            '    """Get user."""\n'
            "    try:\n        return name\n"
            "    except ValueError:\n        raise\n"
        )
        all_patterns = []
        all_patterns.extend(
            ts_extract_naming(
                _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
            )
        )
        all_patterns.extend(
            ts_extract_error_handling(
                _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
            )
        )
        all_patterns.extend(
            ts_extract_imports(
                _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
            )
        )
        all_patterns.extend(
            ts_extract_documentation(
                _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
            )
        )
        all_patterns.extend(
            ts_extract_style(
                _parse(source, Language.PYTHON, FAKE_PATH), source, Language.PYTHON, FAKE_PATH
            )
        )
        all_patterns.extend(
            ts_extract_logging(
                _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
            )
        )

        for pat in all_patterns:
            assert isinstance(pat.category, PatternCategory)
            assert isinstance(pat.confidence, Confidence)
            assert pat.language == Language.PYTHON
            assert len(pat.description) > 0
            assert len(pat.name) > 0

    def test_naming_pattern_names_match_regex(self) -> None:
        """The tree-sitter extractor should use the same pattern names as regex."""
        source = "def get_user():\n    pass\n\nclass UserService:\n    pass\n"
        patterns = ts_extract_naming(
            _parse(source, Language.PYTHON, FAKE_PATH), Language.PYTHON, FAKE_PATH
        )
        names = {p.name for p in patterns}
        # These are the same names the regex extractor uses
        assert names <= {"function_naming", "class_naming", "decorator_usage"}
