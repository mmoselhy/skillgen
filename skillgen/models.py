"""Data structures shared across all skillgen modules."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

# --- Enums ---


class Language(enum.Enum):
    """Supported programming languages."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    CPP = "cpp"

    @property
    def display_name(self) -> str:
        names: dict[str, str] = {
            "python": "Python",
            "typescript": "TypeScript",
            "javascript": "JavaScript",
            "java": "Java",
            "go": "Go",
            "rust": "Rust",
            "cpp": "C++",
        }
        return names[self.value]

    @property
    def extensions(self) -> list[str]:
        ext_map: dict[str, list[str]] = {
            "python": [".py", ".pyi"],
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx"],
            "java": [".java"],
            "go": [".go"],
            "rust": [".rs"],
            "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
        }
        return ext_map[self.value]

    @property
    def glob_patterns(self) -> list[str]:
        return [f"*{ext}" for ext in self.extensions]


class PatternCategory(enum.Enum):
    """The 8+ pattern categories extracted by the analyzer."""

    NAMING = "naming-conventions"
    ERROR_HANDLING = "error-handling"
    TESTING = "testing"
    IMPORTS = "imports-and-dependencies"
    DOCUMENTATION = "documentation"
    ARCHITECTURE = "architecture"
    STYLE = "code-style"
    LOGGING = "logging-and-observability"

    @property
    def skill_name(self) -> str:
        """The filename-safe name used for output files."""
        return self.value

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        return self.value.replace("-", " ").title()

    @property
    def description(self) -> str:
        """Short description of this category."""
        descriptions: dict[str, str] = {
            "naming-conventions": "Naming conventions for functions, classes, variables, and files.",
            "error-handling": "How to create, wrap, propagate, and log errors.",
            "testing": "Test framework, file organization, fixtures, assertion style.",
            "imports-and-dependencies": "Import ordering, grouping, approved packages.",
            "documentation": "Docstring format, comment style, documentation conventions.",
            "architecture": "Directory layout, module boundaries, dependency flow.",
            "code-style": "Formatting, line length, quote style, linter/formatter usage.",
            "logging-and-observability": "Logger setup, structured fields, log level usage.",
        }
        return descriptions[self.value]

    @property
    def always_apply(self) -> bool:
        """Whether this category should always apply in Cursor rules."""
        return self in (PatternCategory.ARCHITECTURE, PatternCategory.STYLE)


class OutputFormat(enum.StrEnum):
    """Target output format."""

    CLAUDE = "claude"
    CURSOR = "cursor"
    ALL = "all"


class Confidence(enum.Enum):
    """Confidence level for an extracted pattern."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --- Core Data Structures ---


@dataclass
class LanguageInfo:
    """Information about a detected language in the project."""

    language: Language
    file_count: int
    file_paths: list[Path] = field(default_factory=list, repr=False)
    percentage: float = 0.0


@dataclass
class FrameworkInfo:
    """Information about a detected framework."""

    name: str
    language: Language
    evidence: str
    version: str | None = None


@dataclass
class ProjectInfo:
    """Complete description of a detected project."""

    root_path: Path
    languages: list[LanguageInfo]
    frameworks: list[FrameworkInfo]
    total_files: int
    source_files: int
    config_files: list[Path] = field(default_factory=list)
    manifest_files: list[Path] = field(default_factory=list)

    @property
    def language_names(self) -> list[str]:
        return [li.language.display_name for li in self.languages]

    @property
    def primary_language(self) -> LanguageInfo:
        return max(self.languages, key=lambda li: li.file_count)


@dataclass
class CodePattern:
    """A single extracted code pattern with evidence and confidence."""

    category: PatternCategory
    name: str
    description: str
    evidence: list[str]
    confidence: Confidence
    prevalence: float = 1.0
    language: Language | None = None
    file_path: Path | None = None
    conflict: str | None = None

    @property
    def is_conflicted(self) -> bool:
        return self.conflict is not None


@dataclass
class SkillDefinition:
    """A generated skill file's content and metadata."""

    name: str
    description: str
    category: PatternCategory
    content: str
    languages: list[str]
    glob_patterns: list[str] = field(default_factory=list)
    always_apply: bool = False


@dataclass
class AnalysisResult:
    """Complete analysis result."""

    project_info: ProjectInfo
    patterns: list[CodePattern]
    files_analyzed: int
    files_skipped: int = 0
    analysis_duration_seconds: float = 0.0

    def patterns_by_category(self, category: PatternCategory) -> list[CodePattern]:
        return [p for p in self.patterns if p.category == category]

    def patterns_by_language(self, language: Language) -> list[CodePattern]:
        return [p for p in self.patterns if p.language == language]

    @property
    def categories_with_patterns(self) -> list[PatternCategory]:
        return list({p.category for p in self.patterns})


@dataclass
class GenerationResult:
    """Result of skill generation."""

    skills: list[SkillDefinition]
    stats: dict[str, int]
    timing_seconds: float

    @property
    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]


@dataclass
class WrittenFile:
    """Record of a file written (or that would be written in dry-run mode)."""

    path: Path
    format: str
    line_count: int
    dry_run: bool = False


# --- Synthesizer Data Structures ---


@dataclass
class ConventionEntry:
    """A single synthesized convention with project-wide stats."""

    name: str
    description: str
    prevalence: float  # 0.0-1.0 fraction of analyzed files showing this
    file_count: int
    total_files: int
    confidence: Confidence
    evidence: list[str]  # deduplicated top examples (max 5)
    language: Language | None = None
    conflict: str | None = None


@dataclass
class CategorySummary:
    """Synthesized conventions for one pattern category."""

    category: PatternCategory
    entries: list[ConventionEntry]  # ranked by prevalence descending
    files_analyzed: int
    raw_pattern_count: int  # before dedup
    config_values: dict[str, str] = field(default_factory=dict)  # from parsed config files

    @property
    def confidence_level(self) -> Confidence:
        """Overall confidence for this category based on file count and pattern diversity."""
        if self.files_analyzed >= 20 and len(self.entries) >= 3:
            return Confidence.HIGH
        if self.files_analyzed >= 5 and len(self.entries) >= 2:
            return Confidence.MEDIUM
        return Confidence.LOW


@dataclass
class ProjectConventions:
    """Complete synthesized project conventions -- the output of the synthesizer."""

    project_info: ProjectInfo
    categories: dict[PatternCategory, CategorySummary]
    config_settings: dict[str, str]
    config_files_parsed: list[str]
    files_analyzed: int
    analysis_duration_seconds: float
    synthesis_duration_seconds: float = 0.0


# --- Enricher Data Structures ---


@dataclass
class IndexEntry:
    """A single skill entry from the online skill index."""

    id: str
    name: str
    language: str
    framework: str | None
    categories: list[str]
    path: str
    description: str
    # v2 fields (optional, with backward-compatible defaults)
    source_repo: str = ""
    content_url: str = ""
    trust: str = "contributed"
    format: str = "markdown"
    tags: list[str] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class EnrichmentResult:
    """Result of searching the online skill index."""

    matched: list[IndexEntry]
    skipped_categories: list[str]
    errors: list[str] = field(default_factory=list)
