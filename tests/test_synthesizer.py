"""Tests for the synthesizer module."""

from __future__ import annotations

from pathlib import Path

from skillgen.models import (
    AnalysisResult,
    CodePattern,
    Confidence,
    Language,
    LanguageInfo,
    PatternCategory,
    ProjectConventions,
    ProjectInfo,
)
from skillgen.synthesizer import synthesize


def _make_project_info(root: Path | None = None) -> ProjectInfo:
    """Create a minimal ProjectInfo for tests."""
    return ProjectInfo(
        root_path=root or Path("/test/project"),
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
    )


def _make_analysis(
    patterns: list[CodePattern],
    root: Path | None = None,
    files_analyzed: int = 30,
) -> AnalysisResult:
    """Create a test AnalysisResult."""
    return AnalysisResult(
        project_info=_make_project_info(root),
        patterns=patterns,
        files_analyzed=files_analyzed,
        analysis_duration_seconds=0.5,
    )


def _make_pattern(
    category: PatternCategory,
    name: str,
    description: str,
    *,
    evidence: list[str] | None = None,
    confidence: Confidence = Confidence.HIGH,
    language: Language = Language.PYTHON,
    file_path: str = "test.py",
) -> CodePattern:
    """Create a test CodePattern."""
    return CodePattern(
        category=category,
        name=name,
        description=description,
        evidence=evidence or [f"ev_{name}"],
        confidence=confidence,
        language=language,
        file_path=Path(file_path),
    )


class TestDeduplication:
    """Test pattern deduplication across files."""

    def test_identical_patterns_merged(self) -> None:
        """5 identical patterns from 5 files -> 1 entry with file_count=5."""
        patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"file_{i}.py",
                evidence=[f"func_{i}"],
            )
            for i in range(5)
        ]

        analysis = _make_analysis(patterns, files_analyzed=30)
        conventions = synthesize(analysis)

        naming = conventions.categories.get(PatternCategory.NAMING)
        assert naming is not None
        # Should have exactly 1 entry (all had same name + description).
        entries = [e for e in naming.entries if e.name == "function_naming"]
        assert len(entries) == 1
        assert entries[0].file_count == 5

    def test_evidence_merged_and_capped(self) -> None:
        """Evidence lists should be merged and capped at 5."""
        patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"file_{i}.py",
                evidence=[f"ev_unique_{i}_a", f"ev_unique_{i}_b"],
            )
            for i in range(5)
        ]

        analysis = _make_analysis(patterns)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        entry = next(e for e in naming.entries if e.name == "function_naming")
        # Should have at most 5 evidence items.
        assert len(entry.evidence) <= 5
        # Should all be unique.
        assert len(entry.evidence) == len(set(entry.evidence))


class TestPrevalenceComputation:
    """Test prevalence stat computation."""

    def test_prevalence_computed_correctly(self) -> None:
        """30 snake_case + 5 camelCase -> 86% prevalence for snake_case."""
        snake_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"snake_{i}.py",
            )
            for i in range(30)
        ]
        camel_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use camelCase",
                file_path=f"camel_{i}.py",
            )
            for i in range(5)
        ]

        analysis = _make_analysis(snake_patterns + camel_patterns, files_analyzed=35)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        # Should be sorted by prevalence descending.
        assert naming.entries[0].description == "Functions use snake_case"
        # Check approximate prevalence.
        assert naming.entries[0].file_count == 30
        assert naming.entries[0].prevalence > 0.8

    def test_conflict_detected(self) -> None:
        """Two naming styles should produce conflict annotations."""
        snake_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"snake_{i}.py",
            )
            for i in range(30)
        ]
        camel_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use camelCase",
                file_path=f"camel_{i}.py",
            )
            for i in range(5)
        ]

        analysis = _make_analysis(snake_patterns + camel_patterns, files_analyzed=35)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        # The dominant entry should have a conflict note.
        dominant = naming.entries[0]
        assert dominant.conflict is not None
        assert "camelCase" in dominant.conflict


class TestConfigParsing:
    """Test config file parsing."""

    def test_ruff_toml_parsed(self, tmp_path: Path) -> None:
        """Create a tmp ruff.toml with line-length=100, verify it's in config_settings."""
        ruff_toml = tmp_path / "ruff.toml"
        ruff_toml.write_text('line-length = 100\n\n[lint]\nselect = ["E", "F"]\n')

        analysis = _make_analysis(
            [
                _make_pattern(
                    PatternCategory.STYLE,
                    "line_length",
                    "Max line length is 100",
                ),
            ],
            root=tmp_path,
        )

        conventions = synthesize(analysis)

        assert "ruff.line-length" in conventions.config_settings
        assert conventions.config_settings["ruff.line-length"] == "100"
        assert "ruff.select" in conventions.config_settings
        assert "ruff.toml" in conventions.config_files_parsed

    def test_pyproject_ruff_parsed(self, tmp_path: Path) -> None:
        """Parse ruff config from pyproject.toml [tool.ruff]."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.ruff]\nline-length = 88\n\n[tool.ruff.lint]\nselect = ['E', 'F', 'W']\n"
        )

        analysis = _make_analysis(
            [_make_pattern(PatternCategory.STYLE, "line_length", "Max line length is 88")],
            root=tmp_path,
        )
        conventions = synthesize(analysis)

        assert conventions.config_settings.get("ruff.line-length") == "88"

    def test_prettierrc_parsed(self, tmp_path: Path) -> None:
        """Parse .prettierrc JSON settings."""
        prettierrc = tmp_path / ".prettierrc"
        prettierrc.write_text('{"singleQuote": true, "semi": false, "tabWidth": 2}')

        analysis = _make_analysis(
            [_make_pattern(PatternCategory.STYLE, "quote_style", "Uses single quotes")],
            root=tmp_path,
        )
        conventions = synthesize(analysis)

        assert conventions.config_settings.get("prettier.singleQuote") == "true"
        assert conventions.config_settings.get("prettier.semi") == "false"
        assert conventions.config_settings.get("prettier.tabWidth") == "2"

    def test_mypy_from_pyproject(self, tmp_path: Path) -> None:
        """Parse mypy settings from pyproject.toml [tool.mypy]."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.mypy]\nstrict = true\npython_version = "3.11"\n')

        analysis = _make_analysis(
            [_make_pattern(PatternCategory.STYLE, "type_hints", "Uses type hints")],
            root=tmp_path,
        )
        conventions = synthesize(analysis)

        assert conventions.config_settings.get("mypy.strict") == "true"
        assert conventions.config_settings.get("mypy.python_version") == "3.11"

    def test_config_parsing_never_crashes(self, tmp_path: Path) -> None:
        """Malformed config files should not crash the synthesizer."""
        ruff_toml = tmp_path / "ruff.toml"
        ruff_toml.write_text("this is not valid toml {{{}}")

        prettierrc = tmp_path / ".prettierrc"
        prettierrc.write_text("{invalid json")

        analysis = _make_analysis(
            [_make_pattern(PatternCategory.STYLE, "line_length", "Max line length")],
            root=tmp_path,
        )

        # Should not raise.
        conventions = synthesize(analysis)
        assert isinstance(conventions, ProjectConventions)


class TestFiltering:
    """Test low-value entry filtering."""

    def test_low_confidence_low_prevalence_filtered(self) -> None:
        """LOW confidence + <10% prevalence patterns are dropped."""
        patterns = [
            # High confidence, keep.
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path="main.py",
                confidence=Confidence.HIGH,
            ),
            # Low confidence but only in 1 file out of many -> should be filtered.
            _make_pattern(
                PatternCategory.NAMING,
                "rare_convention",
                "Some rare naming pattern",
                file_path="rare.py",
                confidence=Confidence.LOW,
            ),
        ]

        analysis = _make_analysis(patterns, files_analyzed=50)
        conventions = synthesize(analysis)

        naming = conventions.categories.get(PatternCategory.NAMING)
        assert naming is not None
        entry_names = [e.name for e in naming.entries]
        # The rare_convention with LOW confidence and low prevalence (1/50 = 2%) should be dropped.
        assert "rare_convention" not in entry_names
        assert "function_naming" in entry_names


class TestEmptyInput:
    """Test with no patterns."""

    def test_empty_patterns_produce_empty_categories(self) -> None:
        """0 patterns -> empty categories dict."""
        analysis = _make_analysis([], files_analyzed=0)
        conventions = synthesize(analysis)

        assert len(conventions.categories) == 0
        assert conventions.files_analyzed == 0


class TestSynthesisTiming:
    """Test that synthesis timing is recorded."""

    def test_synthesis_duration_recorded(self) -> None:
        patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
            )
        ]
        analysis = _make_analysis(patterns)
        conventions = synthesize(analysis)

        assert conventions.synthesis_duration_seconds >= 0.0


class TestAntiPatterns:
    """Test anti-pattern computation from minority conventions."""

    def test_anti_pattern_generated_for_minority(self) -> None:
        """When dominant pattern is >80%, minority should produce anti-pattern."""
        snake_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"snake_{i}.py",
            )
            for i in range(30)
        ]
        camel_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use camelCase",
                file_path=f"camel_{i}.py",
            )
            for i in range(3)
        ]

        analysis = _make_analysis(snake_patterns + camel_patterns, files_analyzed=33)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        assert len(naming.anti_patterns) >= 1
        assert any("camelCase" in ap for ap in naming.anti_patterns)

    def test_no_anti_pattern_when_close_split(self) -> None:
        """When patterns are close (60/40), no anti-patterns should be generated."""
        snake_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"snake_{i}.py",
            )
            for i in range(18)
        ]
        camel_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use camelCase",
                file_path=f"camel_{i}.py",
            )
            for i in range(12)
        ]

        analysis = _make_analysis(snake_patterns + camel_patterns, files_analyzed=30)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        assert len(naming.anti_patterns) == 0

    def test_no_anti_pattern_for_single_variant(self) -> None:
        """Single convention with no competing variant -> no anti-patterns."""
        patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"file_{i}.py",
            )
            for i in range(20)
        ]

        analysis = _make_analysis(patterns, files_analyzed=20)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        assert len(naming.anti_patterns) == 0

    def test_anti_pattern_uses_do_not_phrasing(self) -> None:
        """Anti-patterns should start with 'Do NOT'."""
        snake_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use snake_case",
                file_path=f"snake_{i}.py",
            )
            for i in range(30)
        ]
        camel_patterns = [
            _make_pattern(
                PatternCategory.NAMING,
                "function_naming",
                "Functions use camelCase",
                file_path=f"camel_{i}.py",
            )
            for i in range(2)
        ]

        analysis = _make_analysis(snake_patterns + camel_patterns, files_analyzed=32)
        conventions = synthesize(analysis)

        naming = conventions.categories[PatternCategory.NAMING]
        for ap in naming.anti_patterns:
            assert ap.startswith("Do NOT"), f"Anti-pattern should start with 'Do NOT': {ap}"
