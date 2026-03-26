"""Skill content generation: local template engine and optional LLM enhancement."""

from __future__ import annotations

import enum
import os
import time
import warnings
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from skillgen.models import (
    AnalysisResult,
    CodePattern,
    Confidence,
    GenerationResult,
    Language,
    PatternCategory,
    ProjectInfo,
    SkillDefinition,
)

# Type alias for category renderer functions.
_RendererFunc = Callable[[PatternCategory, list[CodePattern], ProjectInfo], str]


class GenerationMode(enum.Enum):
    LOCAL = "local"
    LLM = "llm"


class SkillGenerator(ABC):
    """Abstract base for skill generators."""

    @abstractmethod
    def generate(self, analysis: AnalysisResult) -> GenerationResult: ...


class LocalGenerator(SkillGenerator):
    """Rule-based generator using string templates. No network access. Deterministic output."""

    MIN_PATTERNS_PER_SKILL = 3

    def generate(self, analysis: AnalysisResult) -> GenerationResult:
        start = time.monotonic()
        skills: list[SkillDefinition] = []

        for category in PatternCategory:
            category_patterns = analysis.patterns_by_category(category)
            if len(category_patterns) < self.MIN_PATTERNS_PER_SKILL:
                continue

            content = self._render_skill(category, category_patterns, analysis.project_info)
            # Determine glob patterns from languages present in patterns
            langs_in_patterns: set[Language] = set()
            for p in category_patterns:
                if p.language is not None:
                    langs_in_patterns.add(p.language)

            glob_patterns: list[str] = []
            for lang_enum in langs_in_patterns:
                glob_patterns.extend(lang_enum.glob_patterns)

            skill = SkillDefinition(
                name=category.skill_name,
                description=category.description,
                category=category,
                content=content,
                languages=analysis.project_info.language_names,
                glob_patterns=glob_patterns if glob_patterns else ["*"],
                always_apply=category.always_apply,
            )
            skills.append(skill)

        elapsed = time.monotonic() - start
        return GenerationResult(
            skills=skills,
            stats={
                "categories_attempted": len(PatternCategory),
                "skills_generated": len(skills),
                "patterns_total": len(analysis.patterns),
            },
            timing_seconds=elapsed,
        )

    def _render_skill(
        self,
        category: PatternCategory,
        patterns: list[CodePattern],
        project_info: ProjectInfo,
    ) -> str:
        """Render a single skill file's Markdown content from patterns."""
        renderer = _CATEGORY_RENDERERS.get(category, _render_generic)
        return renderer(category, patterns, project_info)


class LLMGenerator(SkillGenerator):
    """LLM-enhanced generator. Falls back to LocalGenerator on failure."""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or self._detect_provider()
        self._client: Any = self._init_client()
        self._fallback = LocalGenerator()

    def _detect_provider(self) -> str:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        raise OSError(
            "No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
            "or use --llm-provider to specify a provider."
        )

    def _init_client(self) -> Any:
        if self.provider == "anthropic":
            from anthropic import Anthropic

            return Anthropic()
        elif self.provider == "openai":
            from openai import OpenAI

            return OpenAI()
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def generate(self, analysis: AnalysisResult) -> GenerationResult:
        try:
            return self._generate_with_llm(analysis)
        except Exception as exc:
            warnings.warn(
                f"LLM generation failed ({exc}). Falling back to local generation.",
                stacklevel=2,
            )
            return self._fallback.generate(analysis)

    def _generate_with_llm(self, analysis: AnalysisResult) -> GenerationResult:
        """Generate skills using LLM API calls."""
        start = time.monotonic()
        local_result = self._fallback.generate(analysis)

        enhanced_skills: list[SkillDefinition] = []
        for skill in local_result.skills:
            try:
                enhanced_content = self._enhance_skill(skill, analysis)
                enhanced_skills.append(
                    SkillDefinition(
                        name=skill.name,
                        description=skill.description,
                        category=skill.category,
                        content=enhanced_content,
                        languages=skill.languages,
                        glob_patterns=skill.glob_patterns,
                        always_apply=skill.always_apply,
                    )
                )
            except Exception:
                enhanced_skills.append(skill)

        elapsed = time.monotonic() - start
        return GenerationResult(
            skills=enhanced_skills,
            stats={
                "categories_attempted": local_result.stats.get("categories_attempted", 0),
                "skills_generated": len(enhanced_skills),
                "patterns_total": local_result.stats.get("patterns_total", 0),
                "llm_enhanced": 1,
            },
            timing_seconds=elapsed,
        )

    def _enhance_skill(self, skill: SkillDefinition, analysis: AnalysisResult) -> str:
        """Use LLM to enhance a single skill's content."""
        system_prompt = (
            "You are an expert software engineer. You are given a skill file draft "
            "generated by analyzing a codebase. Improve the content to be more specific, "
            "actionable, and well-organized. Keep it between 20 and 150 lines. "
            "Output ONLY the improved Markdown content, no extra commentary."
        )
        user_prompt = (
            f"Project languages: {', '.join(skill.languages)}\n"
            f"Category: {skill.category.display_name}\n\n"
            f"Draft skill content:\n\n{skill.content}"
        )

        if self.provider == "anthropic":
            return self._call_anthropic(system_prompt, user_prompt)
        else:
            return self._call_openai(system_prompt, user_prompt)

    def _call_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return str(response.content[0].text)

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return str(response.choices[0].message.content)


def generate_skills(
    analysis: AnalysisResult,
    mode: GenerationMode = GenerationMode.LOCAL,
    llm_provider: str | None = None,
) -> GenerationResult:
    """Factory function: create the appropriate generator and run it."""
    if mode == GenerationMode.LLM:
        generator: SkillGenerator = LLMGenerator(provider=llm_provider)
    else:
        generator = LocalGenerator()
    return generator.generate(analysis)


# --- Template Rendering Functions ---


def _deduplicate_patterns(patterns: list[CodePattern]) -> list[CodePattern]:
    """Remove duplicate patterns, keeping the one with highest confidence."""
    seen: dict[str, CodePattern] = {}
    confidence_order = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
    for p in patterns:
        key = f"{p.name}:{p.description}"
        if key not in seen or confidence_order.get(p.confidence, 0) > confidence_order.get(
            seen[key].confidence, 0
        ):
            seen[key] = p
    return list(seen.values())


def _group_by_name(patterns: list[CodePattern]) -> dict[str, list[CodePattern]]:
    """Group patterns by name after deduplication."""
    by_name: dict[str, list[CodePattern]] = defaultdict(list)
    for p in patterns:
        by_name[p.name].append(p)
    return by_name


def _get_language_list(patterns: list[CodePattern]) -> str:
    """Get a human-readable list of languages from patterns."""
    langs: set[str] = set()
    for p in patterns:
        if p.language is not None:
            langs.add(p.language.display_name)
    return ", ".join(sorted(langs)) if langs else "the project"


def _format_evidence(evidence: list[str], max_items: int = 3) -> str:
    """Format evidence as bullet list."""
    lines: list[str] = []
    for item in evidence[:max_items]:
        clean = item.strip()
        if clean:
            lines.append(f"  - `{clean}`")
    return "\n".join(lines)


def _render_naming(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render naming conventions skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"This project ({langs}) follows these naming conventions.",
        "",
    ]

    # Group by pattern name
    by_name = _group_by_name(patterns)

    if "function_naming" in by_name:
        lines.append("## Function Naming")
        for p in by_name["function_naming"][:3]:
            lines.append(f"- {p.description}")
            if p.evidence:
                lines.append(f"  - Examples: {', '.join(f'`{e}`' for e in p.evidence[:3])}")
            if p.conflict:
                lines.append(f"  - Note: {p.conflict}")
        lines.append("")

    if "class_naming" in by_name:
        lines.append("## Class/Type Naming")
        for p in by_name["class_naming"][:3]:
            lines.append(f"- {p.description}")
            if p.evidence:
                lines.append(f"  - Examples: {', '.join(f'`{e}`' for e in p.evidence[:3])}")
        lines.append("")

    # File naming guidance based on language
    lines.append("## File Naming")
    for lang_info in project_info.languages:
        lang = lang_info.language
        if lang == Language.PYTHON:
            lines.append("- Python files: `snake_case.py`")
        elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
            lines.append(
                "- TypeScript/JavaScript files: `kebab-case.ts` or `PascalCase.tsx` for components"
            )
        elif lang == Language.GO:
            lines.append("- Go files: `lowercase.go` or `snake_case.go`")
        elif lang == Language.RUST:
            lines.append("- Rust files: `snake_case.rs`")
        elif lang == Language.JAVA:
            lines.append("- Java files: `PascalCase.java` matching the class name")
        elif lang == Language.CPP:
            lines.append("- C++ files: `snake_case.cpp` / `snake_case.h`")
    lines.append("")

    return "\n".join(lines)


def _render_error_handling(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render error handling skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Error handling conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    for name, group in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for p in group[:3]:
            lines.append(f"- {p.description}")
            if p.evidence:
                for ev in p.evidence[:2]:
                    lines.append(f"  - `{ev}`")
        lines.append("")

    # Language-specific guidance
    lines.append("## Guidelines")
    for lang_info in project_info.languages:
        lang = lang_info.language
        if lang == Language.PYTHON:
            lines.append("- Always catch specific exception types, not bare `except:`")
            lines.append("- Use custom exception classes for domain errors")
            lines.append("- Re-raise with `raise ... from err` to preserve tracebacks")
        elif lang == Language.GO:
            lines.append("- Always check `err != nil` after function calls that return errors")
            lines.append('- Wrap errors with context: `fmt.Errorf("doing X: %w", err)`')
            lines.append("- Never use `panic` outside of initialization code")
        elif lang == Language.RUST:
            lines.append("- Prefer `?` operator over `.unwrap()` in production code")
            lines.append("- Define custom error types with `thiserror` or manual `impl`")
            lines.append("- Use `Result<T, E>` for all fallible operations")
        elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
            lines.append("- Use typed error classes that extend `Error`")
            lines.append("- Always provide meaningful error messages")
            lines.append("- Use try/catch at API boundaries")
        elif lang == Language.JAVA:
            lines.append("- Use checked exceptions for recoverable conditions")
            lines.append("- Use runtime exceptions for programming errors")
            lines.append("- Always include original exception in wrapped errors")
    lines.append("")

    return "\n".join(lines)


def _render_testing(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render testing skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Testing conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    if "test_framework" in by_name:
        lines.append("## Test Framework")
        for p in by_name["test_framework"][:3]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "test_file_naming" in by_name:
        lines.append("## Test File Naming")
        seen_names: set[str] = set()
        for p in by_name["test_file_naming"]:
            if p.evidence:
                for ev in p.evidence:
                    if ev not in seen_names:
                        seen_names.add(ev)
                        lines.append(f"- Example: `{ev}`")
            if len(seen_names) >= 5:
                break
        lines.append("")

    if "assertion_style" in by_name:
        lines.append("## Assertion Style")
        for p in by_name["assertion_style"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "pytest_fixtures" in by_name:
        lines.append("## Fixtures")
        for p in by_name["pytest_fixtures"][:2]:
            lines.append(f"- {p.description}")
        lines.append("- Define shared fixtures in `conftest.py` at each directory level")
        lines.append("")

    if "mocking" in by_name:
        lines.append("## Mocking")
        for p in by_name["mocking"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "parametrized_tests" in by_name:
        lines.append("## Parameterized Tests")
        for p in by_name["parametrized_tests"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "table_driven_tests" in by_name:
        lines.append("## Table-Driven Tests")
        for p in by_name["table_driven_tests"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    # General testing guidance
    lines.append("## General Guidelines")
    lines.append("- Keep tests focused: one behavior per test function")
    lines.append("- Use descriptive test names that explain the expected behavior")
    lines.append("- Arrange-Act-Assert pattern for test structure")
    lines.append("")

    return "\n".join(lines)


def _render_imports(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render import conventions skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Import and dependency conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    if "import_style" in by_name:
        lines.append("## Import Style")
        for p in by_name["import_style"][:3]:
            lines.append(f"- {p.description}")
            if p.evidence:
                for ev in p.evidence[:2]:
                    if ev:
                        lines.append(f"  - `{ev}`")
        lines.append("")

    if "import_grouping" in by_name:
        lines.append("## Import Grouping")
        for p in by_name["import_grouping"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "barrel_files" in by_name:
        lines.append("## Barrel Files")
        for p in by_name["barrel_files"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "export_control" in by_name:
        lines.append("## Export Control")
        for p in by_name["export_control"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    # Standard grouping guidance
    lines.append("## Import Order")
    for lang_info in project_info.languages:
        lang = lang_info.language
        if lang == Language.PYTHON:
            lines.append("- Group imports in this order:")
            lines.append("  1. Standard library imports")
            lines.append("  2. Third-party imports")
            lines.append("  3. Local/project imports")
            lines.append("- Separate groups with a blank line")
        elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
            lines.append("- Group imports in this order:")
            lines.append("  1. External packages (node_modules)")
            lines.append("  2. Internal aliases/paths")
            lines.append("  3. Relative imports")
        elif lang == Language.GO:
            lines.append("- Go imports are auto-formatted by goimports:")
            lines.append("  1. Standard library")
            lines.append("  2. External packages")
            lines.append("  3. Local packages")
    lines.append("")

    return "\n".join(lines)


def _render_documentation(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render documentation style skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Documentation conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    if "docstring_style" in by_name:
        lines.append("## Docstring Style")
        for p in by_name["docstring_style"][:3]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "module_docstring" in by_name:
        lines.append("## Module-Level Documentation")
        lines.append("- Every module should have a top-level docstring explaining its purpose")
        lines.append("")

    if "jsdoc" in by_name:
        lines.append("## JSDoc")
        for p in by_name["jsdoc"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "go_doc_comments" in by_name:
        lines.append("## Go Doc Comments")
        for p in by_name["go_doc_comments"][:2]:
            lines.append(f"- {p.description}")
        lines.append("- Every exported function and type must have a doc comment")
        lines.append("- Doc comments start with the name of the thing being documented")
        lines.append("")

    if "rust_doc_comments" in by_name:
        lines.append("## Rust Doc Comments")
        for p in by_name["rust_doc_comments"][:2]:
            lines.append(f"- {p.description}")
        lines.append("- Use `///` for item documentation")
        lines.append("- Use `//!` for module-level documentation")
        lines.append("")

    if "javadoc" in by_name:
        lines.append("## Javadoc")
        for p in by_name["javadoc"][:2]:
            lines.append(f"- {p.description}")
        lines.append("- Document all public classes and methods")
        lines.append("")

    lines.append("## General Guidelines")
    lines.append("- Document the 'why', not the 'what'")
    lines.append("- Keep documentation close to the code it describes")
    lines.append("- Update documentation when changing code behavior")
    lines.append("")

    return "\n".join(lines)


def _render_architecture(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render architecture skill."""
    patterns = _deduplicate_patterns(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Project architecture for {', '.join(project_info.language_names)}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    if "top_level_dirs" in by_name:
        lines.append("## Project Structure")
        for p in by_name["top_level_dirs"][:1]:
            lines.append(f"- {p.description}")
            lines.append("")
            lines.append("```")
            for ev in p.evidence:
                lines.append(f"  {ev}")
            lines.append("```")
        lines.append("")

    if "src_directory" in by_name:
        lines.append("## Source Organization")
        lines.append("- Main source code lives under `src/`")
        lines.append("")

    if "layered_architecture" in by_name:
        lines.append("## Architecture Pattern")
        for p in by_name["layered_architecture"][:1]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "go_project_layout" in by_name:
        lines.append("## Go Project Layout")
        for p in by_name["go_project_layout"][:1]:
            lines.append(f"- {p.description}")
        lines.append("- `cmd/` contains application entry points")
        lines.append("- `internal/` contains private application code")
        lines.append("- `pkg/` contains code that can be imported by external projects")
        lines.append("")

    if "test_directory" in by_name:
        lines.append("## Test Organization")
        for p in by_name["test_directory"][:1]:
            lines.append(f"- {p.description}")
        lines.append("")

    # Frameworks
    fw_patterns = [p for p in patterns if p.name.startswith("framework_")]
    if fw_patterns:
        lines.append("## Frameworks")
        for p in fw_patterns:
            lines.append(f"- {p.description}")
        lines.append("")

    lines.append("## Where to Put New Code")
    for lang_info in project_info.languages:
        lang = lang_info.language
        if lang == Language.PYTHON:
            lines.append("- New modules go in the appropriate package under the source directory")
            lines.append("- New tests go in the corresponding `tests/` subdirectory")
        elif lang in (Language.TYPESCRIPT, Language.JAVASCRIPT):
            lines.append("- New components go in `src/components/`")
            lines.append("- New utilities go in `src/utils/` or `src/lib/`")
        elif lang == Language.GO:
            lines.append("- New packages go in `internal/` unless they need external visibility")
            lines.append("- New entry points go in `cmd/<name>/main.go`")
    lines.append("")

    return "\n".join(lines)


def _render_style(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render code style skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Code style conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    if "line_length" in by_name:
        lines.append("## Line Length")
        for p in by_name["line_length"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "quote_style" in by_name:
        lines.append("## Quote Style")
        for p in by_name["quote_style"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "semicolons" in by_name:
        lines.append("## Semicolons")
        for p in by_name["semicolons"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "type_hints" in by_name:
        lines.append("## Type Annotations")
        for p in by_name["type_hints"][:2]:
            lines.append(f"- {p.description}")
        lines.append(
            "- All new functions must include type annotations for parameters and return values"
        )
        lines.append("")

    if "trailing_commas" in by_name:
        lines.append("## Trailing Commas")
        for p in by_name["trailing_commas"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "variable_declaration" in by_name:
        lines.append("## Variable Declarations")
        for p in by_name["variable_declaration"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    # Formatter/linter detection from config files
    config_names = {cf.name for cf in project_info.config_files}
    lines.append("## Formatters and Linters")
    if "ruff.toml" in config_names or any("ruff" in str(p) for p in project_info.config_files):
        lines.append("- Uses **ruff** for linting and formatting")
    if ".flake8" in config_names:
        lines.append("- Uses **flake8** for linting")
    if (
        ".prettierrc" in config_names
        or ".prettierrc.json" in config_names
        or "prettier.config.js" in config_names
    ):
        lines.append("- Uses **Prettier** for formatting")
    if (
        ".eslintrc" in config_names
        or ".eslintrc.js" in config_names
        or ".eslintrc.json" in config_names
    ):
        lines.append("- Uses **ESLint** for linting")
    if "rustfmt.toml" in config_names:
        lines.append("- Uses **rustfmt** for formatting")
    if ".golangci.yml" in config_names or ".golangci.yaml" in config_names:
        lines.append("- Uses **golangci-lint** for linting")
    if ".pylintrc" in config_names:
        lines.append("- Uses **pylint** for linting")
    if ".isort.cfg" in config_names:
        lines.append("- Uses **isort** for import sorting")
    lines.append("")

    return "\n".join(lines)


def _render_logging(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Render logging and observability skill."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"Logging and observability conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    if "logging_library" in by_name:
        lines.append("## Logging Library")
        for p in by_name["logging_library"][:3]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "logger_init" in by_name:
        lines.append("## Logger Initialization")
        for p in by_name["logger_init"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    if "console_logging" in by_name:
        lines.append("## Console Logging")
        for p in by_name["console_logging"][:2]:
            lines.append(f"- {p.description}")
        lines.append("")

    # Log level patterns
    log_levels = [name for name in by_name if name.startswith("log_level_")]
    if log_levels:
        lines.append("## Log Levels in Use")
        for name in sorted(log_levels):
            for p in by_name[name][:1]:
                lines.append(f"- {p.description}")
        lines.append("")

    lines.append("## Guidelines")
    lines.append("- Use structured logging where possible (key-value pairs)")
    lines.append("- Include request/correlation IDs in log entries")
    lines.append(
        "- Use appropriate log levels: DEBUG for development, INFO for operations, ERROR for failures"
    )
    lines.append("- Never log sensitive data (passwords, tokens, PII)")
    lines.append("")

    return "\n".join(lines)


def _render_generic(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """Generic renderer for categories without a specific renderer."""
    patterns = _deduplicate_patterns(patterns)
    langs = _get_language_list(patterns)
    lines: list[str] = [
        f"# {category.display_name}",
        "",
        f"{category.description} Conventions for {langs}.",
        "",
    ]

    by_name = _group_by_name(patterns)

    for name, group in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for p in group[:3]:
            lines.append(f"- {p.description}")
            if p.evidence:
                for ev in p.evidence[:2]:
                    lines.append(f"  - `{ev}`")
        lines.append("")

    return "\n".join(lines)


# Map categories to their renderers.
_CATEGORY_RENDERERS: dict[PatternCategory, _RendererFunc] = {
    PatternCategory.NAMING: _render_naming,
    PatternCategory.ERROR_HANDLING: _render_error_handling,
    PatternCategory.TESTING: _render_testing,
    PatternCategory.IMPORTS: _render_imports,
    PatternCategory.DOCUMENTATION: _render_documentation,
    PatternCategory.ARCHITECTURE: _render_architecture,
    PatternCategory.STYLE: _render_style,
    PatternCategory.LOGGING: _render_logging,
}
