"""Tests for the generator module."""

from __future__ import annotations

from pathlib import Path

from skillgen.analyzer import analyze_project
from skillgen.generator import (
    GenerationMode,
    LocalGenerator,
    generate_skills,
)
from skillgen.models import (
    AnalysisResult,
    CodePattern,
    Confidence,
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


def _make_patterns(
    category: PatternCategory, count: int, lang: Language = Language.PYTHON
) -> list[CodePattern]:
    """Create a list of test patterns for a given category."""
    return [
        CodePattern(
            category=category,
            name=f"test_pattern_{i}",
            description=f"Test pattern {i} for {category.display_name}",
            evidence=[f"evidence_{i}_a", f"evidence_{i}_b"],
            confidence=Confidence.HIGH,
            language=lang,
            file_path=Path(f"test_file_{i}.py"),
        )
        for i in range(count)
    ]


def _make_analysis(patterns: list[CodePattern]) -> AnalysisResult:
    """Create a test AnalysisResult with given patterns."""
    return AnalysisResult(
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
        patterns=patterns,
        files_analyzed=30,
    )


class TestLocalGenerator:
    """Test the local template engine."""

    def test_generates_skills_with_sufficient_patterns(self) -> None:
        patterns: list[CodePattern] = []
        # Add enough patterns for naming and error handling
        patterns.extend(_make_patterns(PatternCategory.NAMING, 5))
        patterns.extend(_make_patterns(PatternCategory.ERROR_HANDLING, 4))

        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        assert len(result.skills) >= 2
        skill_names = [s.name for s in result.skills]
        assert "naming-conventions" in skill_names
        assert "error-handling" in skill_names

    def test_skips_categories_with_few_patterns(self) -> None:
        patterns: list[CodePattern] = []
        patterns.extend(_make_patterns(PatternCategory.NAMING, 5))
        patterns.extend(_make_patterns(PatternCategory.LOGGING, 2))  # Below threshold

        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        skill_names = [s.name for s in result.skills]
        assert "naming-conventions" in skill_names
        assert "logging-and-observability" not in skill_names

    def test_generated_content_is_nonempty(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5)
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        for skill in result.skills:
            assert len(skill.content) > 0
            assert skill.category.display_name in skill.content

    def test_generated_content_has_markdown_structure(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5)
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        for skill in result.skills:
            lines = skill.content.split("\n")
            # Should have at least one heading
            headings = [ln for ln in lines if ln.startswith("#")]
            assert len(headings) >= 1

    def test_stats_are_populated(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5)
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        assert "categories_attempted" in result.stats
        assert "skills_generated" in result.stats
        assert result.stats["skills_generated"] == len(result.skills)

    def test_timing_is_recorded(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5)
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        assert result.timing_seconds >= 0.0

    def test_glob_patterns_set_for_language(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5, Language.PYTHON)
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        for skill in result.skills:
            if skill.name == "naming-conventions":
                assert any("*.py" in g for g in skill.glob_patterns)

    def test_always_apply_for_architecture(self) -> None:
        patterns = _make_patterns(PatternCategory.ARCHITECTURE, 5)
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        for skill in result.skills:
            if skill.name == "architecture":
                assert skill.always_apply is True

    def test_no_skills_from_empty_analysis(self) -> None:
        analysis = _make_analysis([])
        generator = LocalGenerator()
        result = generator.generate(analysis)
        assert len(result.skills) == 0


class TestGenerateSkills:
    """Test the generate_skills factory function."""

    def test_local_mode(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5)
        analysis = _make_analysis(patterns)
        result = generate_skills(analysis, mode=GenerationMode.LOCAL)
        assert len(result.skills) >= 1

    def test_default_mode_is_local(self) -> None:
        patterns = _make_patterns(PatternCategory.NAMING, 5)
        analysis = _make_analysis(patterns)
        result = generate_skills(analysis)
        assert len(result.skills) >= 1


class TestSkillContentQuality:
    """Test that generated skill content is specific and useful."""

    def test_naming_skill_references_patterns(self) -> None:
        patterns = [
            CodePattern(
                category=PatternCategory.NAMING,
                name="function_naming",
                description="Functions use snake_case",
                evidence=["get_user_by_id", "validate_email"],
                confidence=Confidence.HIGH,
                language=Language.PYTHON,
                file_path=Path("utils.py"),
            ),
            CodePattern(
                category=PatternCategory.NAMING,
                name="class_naming",
                description="Classes/types use PascalCase",
                evidence=["UserService", "HttpClient"],
                confidence=Confidence.HIGH,
                language=Language.PYTHON,
                file_path=Path("models.py"),
            ),
            CodePattern(
                category=PatternCategory.NAMING,
                name="function_naming",
                description="Functions use snake_case",
                evidence=["process_request"],
                confidence=Confidence.HIGH,
                language=Language.PYTHON,
                file_path=Path("handler.py"),
            ),
        ]
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        naming_skills = [s for s in result.skills if s.name == "naming-conventions"]
        assert len(naming_skills) == 1
        content = naming_skills[0].content
        # Should reference the actual pattern
        assert "snake_case" in content
        assert "PascalCase" in content

    def test_error_handling_skill_is_specific(self) -> None:
        patterns = [
            CodePattern(
                category=PatternCategory.ERROR_HANDLING,
                name="exception_types",
                description="Uses try/except with types: ValueError, KeyError",
                evidence=["except ValueError", "except KeyError"],
                confidence=Confidence.HIGH,
                language=Language.PYTHON,
                file_path=Path("handler.py"),
            ),
            CodePattern(
                category=PatternCategory.ERROR_HANDLING,
                name="custom_exceptions",
                description="Defines custom exceptions: ValidationError",
                evidence=["class ValidationError"],
                confidence=Confidence.HIGH,
                language=Language.PYTHON,
                file_path=Path("errors.py"),
            ),
            CodePattern(
                category=PatternCategory.ERROR_HANDLING,
                name="raise_style",
                description="Raises: ValueError, NotFoundError",
                evidence=["raise ValueError", "raise NotFoundError"],
                confidence=Confidence.MEDIUM,
                language=Language.PYTHON,
                file_path=Path("service.py"),
            ),
        ]
        analysis = _make_analysis(patterns)
        generator = LocalGenerator()
        result = generator.generate(analysis)

        err_skills = [s for s in result.skills if s.name == "error-handling"]
        assert len(err_skills) == 1
        content = err_skills[0].content
        assert "ValueError" in content or "custom" in content.lower()


class TestEndToEndGeneration:
    """End-to-end tests combining analyzer and generator."""

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
        result = generate_skills(analysis, mode=GenerationMode.LOCAL)

        # Should generate multiple skills
        assert len(result.skills) >= 2
        # Each skill should have non-trivial content
        for skill in result.skills:
            assert len(skill.content.strip()) > 50
            # Content should have markdown structure
            assert "#" in skill.content
