"""Tests for the analyzer module."""

from __future__ import annotations

from pathlib import Path

from skillgen.analyzer import (
    _classify_name,
    _extract_documentation,
    _extract_error_handling,
    _extract_imports,
    _extract_logging,
    _extract_naming,
    _extract_style,
    _extract_testing,
    _select_sample,
    analyze_project,
)
from skillgen.models import (
    Language,
    LanguageInfo,
    PatternCategory,
    ProjectInfo,
)


def _create_file(base: Path, relative: str, content: str = "") -> Path:
    full = base / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


class TestNameClassification:
    """Test the naming convention classifier."""

    def test_snake_case(self) -> None:
        assert _classify_name("get_user_by_id") == "snake_case"
        assert _classify_name("validate_email") == "snake_case"

    def test_camel_case(self) -> None:
        assert _classify_name("getUserById") == "camelCase"
        assert _classify_name("validateEmail") == "camelCase"

    def test_pascal_case(self) -> None:
        assert _classify_name("UserService") == "PascalCase"
        assert _classify_name("HttpClient") == "PascalCase"

    def test_upper_snake_case(self) -> None:
        assert _classify_name("MAX_RETRIES") == "UPPER_SNAKE_CASE"
        assert _classify_name("API_BASE_URL") == "UPPER_SNAKE_CASE"

    def test_single_lowercase_word(self) -> None:
        # Single lowercase words are compatible with snake_case
        assert _classify_name("name") == "snake_case"

    def test_single_char(self) -> None:
        # Single characters shouldn't be classified
        assert _classify_name("x") is None


class TestNamingExtraction:
    """Test naming pattern extraction from source code."""

    def test_python_functions(self, tmp_path: Path) -> None:
        source = """
def get_user_by_id(user_id: int):
    pass

def validate_email(email: str):
    pass

def process_payment(amount: float):
    pass
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_naming(source, Language.PYTHON, fp)
        func_patterns = [p for p in patterns if p.name == "function_naming"]
        assert len(func_patterns) >= 1
        assert "snake_case" in func_patterns[0].description

    def test_typescript_classes(self, tmp_path: Path) -> None:
        source = """
class UserService {
    constructor() {}
}

class HttpClient {
    fetch() {}
}

function getUserById(id: string) {
    return null;
}
"""
        fp = tmp_path / "example.ts"
        fp.write_text(source)
        patterns = _extract_naming(source, Language.TYPESCRIPT, fp)
        class_patterns = [p for p in patterns if p.name == "class_naming"]
        assert len(class_patterns) >= 1
        assert "PascalCase" in class_patterns[0].description

    def test_go_functions(self, tmp_path: Path) -> None:
        source = """
func GetUserByID(id string) (*User, error) {
    return nil, nil
}

func (s *Service) HandleRequest(w http.ResponseWriter, r *http.Request) {
}

type UserService struct {
    db *sql.DB
}
"""
        fp = tmp_path / "example.go"
        fp.write_text(source)
        patterns = _extract_naming(source, Language.GO, fp)
        assert len(patterns) >= 1


class TestErrorHandlingExtraction:
    """Test error handling pattern extraction."""

    def test_python_try_except(self, tmp_path: Path) -> None:
        source = """
try:
    result = do_something()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
except KeyError:
    pass
except Exception as e:
    raise RuntimeError("failed") from e
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_error_handling(source, Language.PYTHON, fp)
        assert len(patterns) >= 1
        categories = [p.category for p in patterns]
        assert PatternCategory.ERROR_HANDLING in categories

    def test_python_custom_exceptions(self, tmp_path: Path) -> None:
        source = """
class ValidationError(Exception):
    pass

class NotFoundError(Exception):
    def __init__(self, entity: str, id: int):
        super().__init__(f"{entity} {id} not found")
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_error_handling(source, Language.PYTHON, fp)
        custom = [p for p in patterns if p.name == "custom_exceptions"]
        assert len(custom) >= 1
        assert "ValidationError" in custom[0].description

    def test_go_error_handling(self, tmp_path: Path) -> None:
        source = """
func doSomething() error {
    result, err := someFunc()
    if err != nil {
        return fmt.Errorf("doing something: %w", err)
    }
    return nil
}
"""
        fp = tmp_path / "example.go"
        fp.write_text(source)
        patterns = _extract_error_handling(source, Language.GO, fp)
        assert len(patterns) >= 1
        err_check = [p for p in patterns if p.name == "err_nil_check"]
        assert len(err_check) >= 1

    def test_rust_result_type(self, tmp_path: Path) -> None:
        source = """
fn read_file(path: &str) -> Result<String, io::Error> {
    let content = fs::read_to_string(path)?;
    Ok(content)
}
"""
        fp = tmp_path / "example.rs"
        fp.write_text(source)
        patterns = _extract_error_handling(source, Language.RUST, fp)
        result_patterns = [p for p in patterns if p.name == "result_type"]
        assert len(result_patterns) >= 1

    def test_typescript_try_catch(self, tmp_path: Path) -> None:
        source = """
async function fetchUser(id: string) {
    try {
        const response = await fetch(`/users/${id}`);
        return response.json();
    } catch (error) {
        console.error('Failed to fetch user:', error);
        throw error;
    }
}

class ApiError extends Error {
    constructor(public statusCode: number, message: string) {
        super(message);
    }
}
"""
        fp = tmp_path / "example.ts"
        fp.write_text(source)
        patterns = _extract_error_handling(source, Language.TYPESCRIPT, fp)
        assert len(patterns) >= 1


class TestTestingExtraction:
    """Test testing pattern extraction."""

    def test_pytest_detection(self, tmp_path: Path) -> None:
        source = """
import pytest

@pytest.fixture
def user():
    return User(name="test")

def test_user_creation(user):
    assert user.name == "test"

@pytest.mark.parametrize("name,expected", [("a", True), ("", False)])
def test_validation(name, expected):
    assert validate(name) == expected
"""
        fp = tmp_path / "test_user.py"
        fp.write_text(source)
        patterns = _extract_testing(source, Language.PYTHON, fp)
        assert len(patterns) >= 1
        fw_patterns = [p for p in patterns if p.name == "test_framework"]
        assert any("pytest" in p.description for p in fw_patterns)

    def test_unittest_detection(self, tmp_path: Path) -> None:
        source = """
import unittest

class TestUser(unittest.TestCase):
    def test_creation(self):
        user = User(name="test")
        self.assertEqual(user.name, "test")
"""
        fp = tmp_path / "test_user.py"
        fp.write_text(source)
        patterns = _extract_testing(source, Language.PYTHON, fp)
        fw_patterns = [p for p in patterns if p.name == "test_framework"]
        assert any("unittest" in p.description for p in fw_patterns)

    def test_jest_detection(self, tmp_path: Path) -> None:
        source = """
describe('UserService', () => {
    test('should create a user', () => {
        const user = createUser('test');
        expect(user.name).toBe('test');
    });
});
"""
        fp = tmp_path / "user.test.ts"
        fp.write_text(source)
        patterns = _extract_testing(source, Language.TYPESCRIPT, fp)
        assert len(patterns) >= 1

    def test_go_table_driven(self, tmp_path: Path) -> None:
        source = """
func TestAdd(t *testing.T) {
    tests := []struct {
        name     string
        a, b     int
        expected int
    }{
        {"positive", 1, 2, 3},
        {"negative", -1, -2, -3},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            assert.Equal(t, tt.expected, Add(tt.a, tt.b))
        })
    }
}
"""
        fp = tmp_path / "math_test.go"
        fp.write_text(source)
        patterns = _extract_testing(source, Language.GO, fp)
        table_patterns = [p for p in patterns if p.name == "table_driven_tests"]
        assert len(table_patterns) >= 1

    def test_non_test_file_skipped(self, tmp_path: Path) -> None:
        source = """
def helper_function():
    pass
"""
        fp = tmp_path / "helper.py"
        fp.write_text(source)
        patterns = _extract_testing(source, Language.PYTHON, fp)
        assert len(patterns) == 0


class TestImportExtraction:
    """Test import style extraction."""

    def test_python_absolute_imports(self, tmp_path: Path) -> None:
        source = """
import os
import sys
from pathlib import Path

from mypackage.utils import helper
from mypackage.models import User
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_imports(source, Language.PYTHON, fp)
        import_style = [p for p in patterns if p.name == "import_style"]
        assert len(import_style) >= 1
        assert "absolute" in import_style[0].description.lower()

    def test_python_relative_imports(self, tmp_path: Path) -> None:
        source = """
from . import utils
from .models import User
from ..common import Base
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_imports(source, Language.PYTHON, fp)
        import_style = [p for p in patterns if p.name == "import_style"]
        assert len(import_style) >= 1
        assert "relative" in import_style[0].description.lower()


class TestDocumentationExtraction:
    """Test documentation pattern extraction."""

    def test_google_style_docstrings(self, tmp_path: Path) -> None:
        source = '''
def get_user(user_id: int) -> User:
    """Get a user by their ID.

    Args:
        user_id: The unique identifier of the user.

    Returns:
        The User object.

    Raises:
        NotFoundError: If the user doesn't exist.
    """
    pass
'''
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_documentation(source, Language.PYTHON, fp)
        doc_patterns = [p for p in patterns if p.name == "docstring_style"]
        assert len(doc_patterns) >= 1
        assert "Google" in doc_patterns[0].description


class TestStyleExtraction:
    """Test code style extraction."""

    def test_python_type_hints(self, tmp_path: Path) -> None:
        source = """
def get_user(user_id: int) -> User:
    pass

def validate(email: str, strict: bool = True) -> bool:
    pass

def process(items: list[str]) -> dict[str, int]:
    pass
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_style(source, Language.PYTHON, fp)
        type_patterns = [p for p in patterns if p.name == "type_hints"]
        assert len(type_patterns) >= 1

    def test_js_no_semicolons(self, tmp_path: Path) -> None:
        source = """
const x = 1
const y = 2
const z = x + y
function foo() {
    return x
}
const bar = () => {
    return y
}
const baz = (a, b) => a + b
export default foo
"""
        fp = tmp_path / "example.js"
        fp.write_text(source)
        patterns = _extract_style(source, Language.JAVASCRIPT, fp)
        semi_patterns = [p for p in patterns if p.name == "semicolons"]
        assert len(semi_patterns) >= 1
        assert (
            "not" in semi_patterns[0].description.lower()
            or "no" in semi_patterns[0].description.lower()
        )


class TestLoggingExtraction:
    """Test logging pattern extraction."""

    def test_python_standard_logging(self, tmp_path: Path) -> None:
        source = """
import logging

logger = logging.getLogger(__name__)

def process():
    logger.info("Processing started")
    logger.debug("Debug details")
    logger.error("Something went wrong")
"""
        fp = tmp_path / "example.py"
        fp.write_text(source)
        patterns = _extract_logging(source, Language.PYTHON, fp)
        lib_patterns = [p for p in patterns if p.name == "logging_library"]
        assert len(lib_patterns) >= 1
        assert (
            "standard logging" in lib_patterns[0].description.lower()
            or "logging module" in lib_patterns[0].description.lower()
        )


class TestFileSampling:
    """Test the file sampling algorithm."""

    def test_respects_max_files(self) -> None:
        files = [Path(f"/project/file_{i}.py") for i in range(100)]
        sample = _select_sample(files, max_files=30)
        assert len(sample) <= 30

    def test_small_projects_get_all_files(self) -> None:
        files = [Path(f"/project/file_{i}.py") for i in range(10)]
        sample = _select_sample(files, max_files=50)
        assert len(sample) == 10

    def test_diverse_directories(self) -> None:
        files = []
        for d in range(10):
            for f in range(10):
                files.append(Path(f"/project/dir_{d}/file_{f}.py"))
        sample = _select_sample(files, max_files=30, max_per_dir=3)
        # Should pick from multiple directories
        dirs_represented = {p.parent for p in sample}
        assert len(dirs_represented) >= 5


class TestAnalyzeProject:
    """Integration tests for the full analysis pipeline."""

    def test_analyze_python_project(self, tmp_path: Path) -> None:
        _create_file(
            tmp_path,
            "main.py",
            '''"""Main module."""
import logging

logger = logging.getLogger(__name__)

def get_user_by_id(user_id: int) -> dict:
    """Get user by ID.

    Args:
        user_id: The user ID.

    Returns:
        User dict.
    """
    try:
        return {"id": user_id}
    except ValueError as e:
        logger.error(f"Error: {e}")
        raise
''',
        )
        _create_file(
            tmp_path,
            "models.py",
            '''"""Data models."""
from dataclasses import dataclass

@dataclass
class User:
    name: str
    email: str

class ValidationError(Exception):
    pass
''',
        )
        _create_file(
            tmp_path,
            "test_main.py",
            """import pytest
from main import get_user_by_id

@pytest.fixture
def user_id():
    return 1

def test_get_user(user_id):
    result = get_user_by_id(user_id)
    assert result["id"] == user_id
""",
        )

        project_info = ProjectInfo(
            root_path=tmp_path,
            languages=[
                LanguageInfo(
                    language=Language.PYTHON,
                    file_count=3,
                    file_paths=[
                        tmp_path / "main.py",
                        tmp_path / "models.py",
                        tmp_path / "test_main.py",
                    ],
                    percentage=100.0,
                ),
            ],
            frameworks=[],
            total_files=3,
            source_files=3,
        )

        result = analyze_project(project_info)
        assert result.files_analyzed >= 2
        assert len(result.patterns) > 0

        # Check that we got patterns in multiple categories
        categories = {p.category for p in result.patterns}
        assert len(categories) >= 2  # At least naming and something else
