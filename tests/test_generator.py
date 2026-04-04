"""Tests for the generator module (evidence-only renderers with ProjectConventions)."""

from __future__ import annotations

from pathlib import Path

from skillgen.analyzer import analyze_project
from skillgen.generator import (
    GenerationMode,
    LocalGenerator,
    generate_skills,
)
from skillgen.models import (
    CategorySummary,
    Confidence,
    ConventionEntry,
    Language,
    LanguageInfo,
    PatternCategory,
    ProjectConventions,
    ProjectInfo,
)
from skillgen.synthesizer import synthesize


def _make_entry(
    name: str,
    description: str,
    *,
    prevalence: float = 0.8,
    file_count: int = 24,
    total_files: int = 30,
    confidence: Confidence = Confidence.HIGH,
    evidence: list[str] | None = None,
    language: Language = Language.PYTHON,
) -> ConventionEntry:
    """Helper to create a ConventionEntry."""
    return ConventionEntry(
        name=name,
        description=description,
        prevalence=prevalence,
        file_count=file_count,
        total_files=total_files,
        confidence=confidence,
        evidence=evidence or [f"example_{name}_1", f"example_{name}_2"],
        language=language,
    )


def _make_conventions(
    entries_by_category: dict[PatternCategory, list[ConventionEntry]],
    *,
    config_settings: dict[str, str] | None = None,
    config_files_parsed: list[str] | None = None,
    files_analyzed: int = 30,
) -> ProjectConventions:
    """Create a test ProjectConventions object."""
    categories: dict[PatternCategory, CategorySummary] = {}
    for cat, entries in entries_by_category.items():
        categories[cat] = CategorySummary(
            category=cat,
            entries=entries,
            files_analyzed=files_analyzed,
            raw_pattern_count=len(entries) * 3,
            config_values={},
        )

    return ProjectConventions(
        project_info=ProjectInfo(
            root_path=Path("/test/project"),
            languages=[
                LanguageInfo(
                    language=Language.PYTHON,
                    file_count=50,
                    file_paths=[],
                    percentage=100.0,
                )
            ],
            frameworks=[],
            total_files=100,
            source_files=50,
        ),
        categories=categories,
        config_settings=config_settings or {},
        config_files_parsed=config_files_parsed or [],
        files_analyzed=files_analyzed,
        analysis_duration_seconds=0.5,
        synthesis_duration_seconds=0.1,
    )


def _create_file(base: Path, relative: str, content: str = "") -> Path:
    full = base / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


class TestLocalGenerator:
    """Test the local template engine with ProjectConventions input."""

    def test_generates_skills_with_entries(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                    _make_entry("class_naming", "Classes use PascalCase"),
                ],
                PatternCategory.ERROR_HANDLING: [
                    _make_entry("exception_types", "Uses try/except with ValueError, KeyError"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        assert len(result.skills) >= 2
        skill_names = [s.name for s in result.skills]
        assert "naming-conventions" in skill_names
        assert "error-handling" in skill_names

    def test_skips_categories_with_no_entries(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        skill_names = [s.name for s in result.skills]
        assert "naming-conventions" in skill_names
        assert "logging-and-observability" not in skill_names

    def test_generated_content_is_nonempty(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        for skill in result.skills:
            assert len(skill.content) > 0
            assert "<!-- Confidence:" in skill.content

    def test_generated_content_has_markdown_structure(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        for skill in result.skills:
            lines = skill.content.split("\n")
            headings = [ln for ln in lines if ln.startswith("###")]
            assert len(headings) >= 1

    def test_stats_are_populated(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        assert "categories_attempted" in result.stats
        assert "skills_generated" in result.stats
        assert result.stats["skills_generated"] == len(result.skills)

    def test_timing_is_recorded(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        assert result.timing_seconds >= 0.0

    def test_glob_patterns_set_for_language(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry(
                        "function_naming", "Functions use snake_case", language=Language.PYTHON
                    ),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        for skill in result.skills:
            if skill.name == "naming-conventions":
                assert any("*.py" in g for g in skill.glob_patterns)

    def test_always_apply_for_architecture(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.ARCHITECTURE: [
                    _make_entry("top_level_dirs", "Standard project layout"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        for skill in result.skills:
            if skill.name == "architecture":
                assert skill.always_apply is True

    def test_no_skills_from_empty_conventions(self) -> None:
        conventions = _make_conventions({})
        generator = LocalGenerator()
        result = generator.generate(conventions)
        assert len(result.skills) == 0


class TestGenerateSkills:
    """Test the generate_skills factory function."""

    def test_local_mode(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )
        result = generate_skills(conventions, mode=GenerationMode.LOCAL)
        assert len(result.skills) >= 1

    def test_default_mode_is_local(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )
        result = generate_skills(conventions)
        assert len(result.skills) >= 1


class TestSkillContentQuality:
    """Test that generated skill content contains actual stats and evidence."""

    def test_naming_skill_contains_stats(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry(
                        "function_naming",
                        "Functions use snake_case",
                        file_count=34,
                        total_files=39,
                        evidence=["detect_project", "analyze_project", "generate_skills"],
                    ),
                    _make_entry(
                        "class_naming",
                        "Classes use PascalCase",
                        file_count=12,
                        total_files=12,
                        evidence=["ProjectInfo", "CodePattern", "SkillDefinition"],
                    ),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        naming_skills = [s for s in result.skills if s.name == "naming-conventions"]
        assert len(naming_skills) == 1
        content = naming_skills[0].content
        # Should contain imperative phrasing, not stats.
        assert "snake_case" in content
        assert "PascalCase" in content
        # Should reference evidence.
        assert "detect_project" in content

    def test_no_static_guidelines_in_output(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.ERROR_HANDLING: [
                    _make_entry("exception_types", "Uses try/except with ValueError"),
                ],
                PatternCategory.LOGGING: [
                    _make_entry("logging_library", "Uses stdlib logging module"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        for skill in result.skills:
            content = skill.content.lower()
            # No static generic guidelines should appear.
            assert "never log sensitive data" not in content
            assert "always catch specific exception" not in content
            assert "use structured logging where possible" not in content

    def test_config_values_appear_in_style_skill(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.STYLE: [
                    _make_entry("line_length", "Max line length is 100"),
                    _make_entry("quote_style", "Uses double quotes"),
                ],
            },
            config_settings={
                "ruff.line-length": "100",
                "ruff.select": "E, F, W, I",
                "mypy.strict": "true",
            },
            config_files_parsed=["pyproject.toml [tool.ruff]", "pyproject.toml [tool.mypy]"],
        )
        # Inject config into the style category.
        conventions.categories[PatternCategory.STYLE].config_values = {
            "ruff.line-length": "100",
            "ruff.select": "E, F, W, I",
            "mypy.strict": "true",
        }

        generator = LocalGenerator()
        result = generator.generate(conventions)

        style_skills = [s for s in result.skills if s.name == "code-style"]
        assert len(style_skills) == 1
        content = style_skills[0].content
        assert "ruff" in content.lower()
        assert "100" in content

    def test_confidence_comment_present(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        for skill in result.skills:
            assert "<!-- Confidence:" in skill.content

    def test_evidence_examples_in_output(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry(
                        "function_naming",
                        "Functions use snake_case",
                        evidence=["get_user_by_id", "validate_email"],
                    ),
                ],
            }
        )

        generator = LocalGenerator()
        result = generator.generate(conventions)

        naming_skills = [s for s in result.skills if s.name == "naming-conventions"]
        assert len(naming_skills) == 1
        content = naming_skills[0].content
        assert "get_user_by_id" in content
        assert "validate_email" in content

    def test_output_uses_imperative_phrasing(self) -> None:
        """Output should use imperative rules, not statistical observations."""
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry(
                        "function_naming",
                        "Functions use snake_case",
                        file_count=34,
                        total_files=39,
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        naming = next(s for s in result.skills if s.name == "naming-conventions")
        content = naming.content
        # Should NOT contain percentages or file counts
        assert "34/39" not in content
        assert "87%" not in content
        # Should contain imperative phrasing
        assert "snake_case" in content

    def test_no_conflict_notes_in_output(self) -> None:
        """Conflict notes should not appear (they introduce anti-patterns to LLM context)."""
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry(
                        "function_naming",
                        "Functions use snake_case",
                    ),
                ],
            }
        )
        # Manually add a conflict
        conventions.categories[PatternCategory.NAMING].entries[0].conflict = "13% use camelCase"
        generator = LocalGenerator()
        result = generator.generate(conventions)
        naming = next(s for s in result.skills if s.name == "naming-conventions")
        assert "Note:" not in naming.content
        assert "camelCase" not in naming.content


class TestEndToEndGeneration:
    """End-to-end tests combining analyzer, synthesizer, and generator."""

    def test_python_project_generates_skills(self, tmp_path: Path) -> None:
        """A realistic Python project should produce multiple skills."""
        _create_file(
            tmp_path,
            "app/main.py",
            '''"""Main application module."""
import logging
from pathlib import Path

from app.models import User
from app.services import UserService

logger = logging.getLogger(__name__)

def create_app() -> None:
    """Create and configure the application."""
    logger.info("Starting application")
    service = UserService()
    try:
        service.initialize()
    except RuntimeError as e:
        logger.error(f"Failed to start: {e}")
        raise
''',
        )
        _create_file(
            tmp_path,
            "app/models.py",
            '''"""Data models."""
from dataclasses import dataclass

@dataclass
class User:
    """A user in the system."""
    name: str
    email: str
    active: bool = True

class ValidationError(Exception):
    """Raised when validation fails."""
    pass

class NotFoundError(Exception):
    """Raised when a resource is not found."""
    pass
''',
        )
        _create_file(
            tmp_path,
            "app/services.py",
            '''"""Business logic services."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class UserService:
    """Service for user operations."""

    def initialize(self) -> None:
        """Initialize the service."""
        logger.info("UserService initialized")

    def get_user(self, user_id: int) -> Optional[dict]:
        """Get a user by ID.

        Args:
            user_id: The user's unique ID.

        Returns:
            User dict or None.
        """
        try:
            return {"id": user_id}
        except Exception as e:
            logger.error(f"Failed to get user: {e}")
            raise
''',
        )
        _create_file(
            tmp_path,
            "tests/test_models.py",
            """import pytest
from app.models import User, ValidationError

@pytest.fixture
def sample_user():
    return User(name="Test", email="test@example.com")

def test_user_creation(sample_user):
    assert sample_user.name == "Test"
    assert sample_user.active is True

def test_validation_error():
    with pytest.raises(ValidationError):
        raise ValidationError("bad input")
""",
        )

        project_info = ProjectInfo(
            root_path=tmp_path,
            languages=[
                LanguageInfo(
                    language=Language.PYTHON,
                    file_count=4,
                    file_paths=[
                        tmp_path / "app" / "main.py",
                        tmp_path / "app" / "models.py",
                        tmp_path / "app" / "services.py",
                        tmp_path / "tests" / "test_models.py",
                    ],
                    percentage=100.0,
                )
            ],
            frameworks=[],
            total_files=4,
            source_files=4,
        )

        analysis = analyze_project(project_info)
        conventions = synthesize(analysis)
        result = generate_skills(conventions, mode=GenerationMode.LOCAL)

        # Should generate multiple skills.
        assert len(result.skills) >= 2
        # Each skill should have non-trivial content.
        for skill in result.skills:
            assert len(skill.content.strip()) > 50
            assert "#" in skill.content


class TestHeadingFormat:
    """Test that rendered content has no # title and uses ### subsections."""

    def test_naming_content_has_no_h1(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                    _make_entry("class_naming", "Classes use PascalCase"),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        naming = next(s for s in result.skills if s.name == "naming-conventions")
        lines = naming.content.split("\n")
        h1_lines = [ln for ln in lines if ln.startswith("# ")]
        assert len(h1_lines) == 0, f"Content should not have # headings: {h1_lines}"

    def test_naming_subsections_use_h3(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                    _make_entry("class_naming", "Classes use PascalCase"),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        naming = next(s for s in result.skills if s.name == "naming-conventions")
        lines = naming.content.split("\n")
        subsection_lines = [ln for ln in lines if ln.startswith("## ") or ln.startswith("### ")]
        for ln in subsection_lines:
            assert ln.startswith("### "), f"Subsection should use ###: {ln}"

    def test_all_renderers_produce_no_h1(self) -> None:
        """Every category renderer should produce content without # headings."""
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry("function_naming", "Functions use snake_case"),
                ],
                PatternCategory.ERROR_HANDLING: [
                    _make_entry("exception_types", "Uses try/except with ValueError"),
                ],
                PatternCategory.TESTING: [
                    _make_entry("test_framework", "Uses pytest"),
                ],
                PatternCategory.IMPORTS: [
                    _make_entry("import_style", "Uses absolute imports"),
                ],
                PatternCategory.DOCUMENTATION: [
                    _make_entry("module_docstring", "Module docstrings present"),
                ],
                PatternCategory.ARCHITECTURE: [
                    _make_entry("top_level_dirs", "Standard layout"),
                ],
                PatternCategory.STYLE: [
                    _make_entry("line_length", "Max 100 chars"),
                ],
                PatternCategory.LOGGING: [
                    _make_entry("logging_library", "Uses stdlib logging"),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        for skill in result.skills:
            lines = skill.content.split("\n")
            # Only check lines outside code fences for h1 headings
            in_fence = False
            h1_lines = []
            for ln in lines:
                if ln.startswith("```"):
                    in_fence = not in_fence
                elif not in_fence and ln.startswith("# "):
                    h1_lines.append(ln)
            assert len(h1_lines) == 0, f"{skill.name} has # headings: {h1_lines}"


class TestCodeSnippets:
    """Test that code snippets are generated for categories with sufficient data."""

    def test_naming_snippet_has_code_fence(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.NAMING: [
                    _make_entry(
                        "function_naming",
                        "Functions use snake_case",
                        evidence=["get_user", "validate_input"],
                    ),
                    _make_entry(
                        "class_naming",
                        "Classes use PascalCase",
                        evidence=["UserService", "DataProcessor"],
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        naming = next(s for s in result.skills if s.name == "naming-conventions")
        assert "```python" in naming.content
        assert "get_user" in naming.content
        assert "### Example" in naming.content

    def test_error_handling_snippet_has_try_except(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.ERROR_HANDLING: [
                    _make_entry(
                        "exception_types",
                        "Uses try/except with ValueError",
                        evidence=["raise ValueError", "raise TypeError"],
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        err = next(s for s in result.skills if s.name == "error-handling")
        assert "```python" in err.content
        assert "try:" in err.content
        assert "except" in err.content

    def test_testing_snippet_has_pytest(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.TESTING: [
                    _make_entry(
                        "test_framework",
                        "Uses pytest framework",
                        evidence=["import pytest"],
                    ),
                    _make_entry(
                        "pytest_fixtures",
                        "Uses pytest fixtures",
                        evidence=["@pytest.fixture"],
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        testing = next(s for s in result.skills if s.name == "testing")
        assert "```python" in testing.content
        assert "def test_" in testing.content
        assert "@pytest.fixture" in testing.content

    def test_imports_snippet_has_grouping(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.IMPORTS: [
                    _make_entry(
                        "import_style",
                        "Uses absolute imports",
                        evidence=["from myproject.models import User"],
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        imports = next(s for s in result.skills if s.name == "imports-and-dependencies")
        assert "```python" in imports.content
        assert "import" in imports.content

    def test_logging_snippet_has_logger(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.LOGGING: [
                    _make_entry(
                        "logging_library",
                        "Uses stdlib logging module",
                        evidence=["import logging"],
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        log = next(s for s in result.skills if s.name == "logging-and-observability")
        assert "```python" in log.content
        assert "logging" in log.content
        assert "logger" in log.content

    def test_documentation_snippet_has_docstring(self) -> None:
        conventions = _make_conventions(
            {
                PatternCategory.DOCUMENTATION: [
                    _make_entry(
                        "docstring_format",
                        "Uses Google-style docstrings",
                        evidence=["Args:", "Returns:"],
                    ),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        doc = next(s for s in result.skills if s.name == "documentation")
        assert "```python" in doc.content
        assert '"""' in doc.content

    def test_style_has_no_snippet(self) -> None:
        """Style category should not have a code snippet (config-driven)."""
        conventions = _make_conventions(
            {
                PatternCategory.STYLE: [
                    _make_entry("line_length", "Max 100 chars"),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        style = next(s for s in result.skills if s.name == "code-style")
        assert "### Example" not in style.content

    def test_architecture_has_no_snippet(self) -> None:
        """Architecture category should not have a snippet (has directory tree already)."""
        conventions = _make_conventions(
            {
                PatternCategory.ARCHITECTURE: [
                    _make_entry("top_level_dirs", "Standard layout"),
                ],
            }
        )
        generator = LocalGenerator()
        result = generator.generate(conventions)
        arch = next(s for s in result.skills if s.name == "architecture")
        assert "### Example" not in arch.content
