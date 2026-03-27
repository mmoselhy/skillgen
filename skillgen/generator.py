"""Skill content generation: evidence-only renderers backed by ProjectConventions."""

from __future__ import annotations

import enum
import os
import time
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from skillgen.models import (
    CategorySummary,
    ConventionEntry,
    GenerationResult,
    Language,
    PatternCategory,
    ProjectConventions,
    SkillDefinition,
)

# Type alias for category renderer functions.
_RendererFunc = Callable[[CategorySummary, ProjectConventions], str]


class GenerationMode(enum.Enum):
    LOCAL = "local"
    LLM = "llm"


class SkillGenerator(ABC):
    """Abstract base for skill generators."""

    @abstractmethod
    def generate(self, conventions: ProjectConventions) -> GenerationResult: ...


class LocalGenerator(SkillGenerator):
    """Rule-based generator using evidence-only renderers. No network access. Deterministic."""

    MIN_ENTRIES_PER_SKILL = 1

    def generate(self, conventions: ProjectConventions) -> GenerationResult:
        start = time.monotonic()
        skills: list[SkillDefinition] = []

        for category in PatternCategory:
            summary = conventions.categories.get(category)
            if summary is None or len(summary.entries) < self.MIN_ENTRIES_PER_SKILL:
                continue

            content = self._render_skill(summary, conventions)

            # Determine glob patterns from languages present in entries.
            langs_in_entries: set[Language] = set()
            for entry in summary.entries:
                if entry.language is not None:
                    langs_in_entries.add(entry.language)

            glob_patterns: list[str] = []
            for lang_enum in langs_in_entries:
                glob_patterns.extend(lang_enum.glob_patterns)

            skill = SkillDefinition(
                name=category.skill_name,
                description=category.description,
                category=category,
                content=content,
                languages=conventions.project_info.language_names,
                glob_patterns=glob_patterns if glob_patterns else ["*"],
                always_apply=category.always_apply,
            )
            skills.append(skill)

        elapsed = time.monotonic() - start

        total_patterns = sum(s.raw_pattern_count for s in conventions.categories.values())
        return GenerationResult(
            skills=skills,
            stats={
                "categories_attempted": len(PatternCategory),
                "skills_generated": len(skills),
                "patterns_total": total_patterns,
            },
            timing_seconds=elapsed,
        )

    def _render_skill(
        self,
        summary: CategorySummary,
        conventions: ProjectConventions,
    ) -> str:
        """Render a single skill file's Markdown content from synthesized conventions."""
        renderer = _CATEGORY_RENDERERS.get(summary.category, _render_generic)
        return renderer(summary, conventions)


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

    def generate(self, conventions: ProjectConventions) -> GenerationResult:
        try:
            return self._generate_with_llm(conventions)
        except Exception as exc:
            warnings.warn(
                f"LLM generation failed ({exc}). Falling back to local generation.",
                stacklevel=2,
            )
            return self._fallback.generate(conventions)

    def _generate_with_llm(self, conventions: ProjectConventions) -> GenerationResult:
        """Generate skills using LLM API calls."""
        start = time.monotonic()
        local_result = self._fallback.generate(conventions)

        enhanced_skills: list[SkillDefinition] = []
        for skill in local_result.skills:
            try:
                enhanced_content = self._enhance_skill(skill, conventions)
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

    def _enhance_skill(self, skill: SkillDefinition, conventions: ProjectConventions) -> str:
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
    conventions: ProjectConventions,
    mode: GenerationMode = GenerationMode.LOCAL,
    llm_provider: str | None = None,
) -> GenerationResult:
    """Factory function: create the appropriate generator and run it."""
    if mode == GenerationMode.LLM:
        generator: SkillGenerator = LLMGenerator(provider=llm_provider)
    else:
        generator = LocalGenerator()
    return generator.generate(conventions)


# ---------------------------------------------------------------------------
# Evidence-Only Rendering Helpers
# ---------------------------------------------------------------------------


def _confidence_comment(summary: CategorySummary) -> str:
    """Markdown comment with confidence level and stats."""
    level = summary.confidence_level.value.upper()
    return (
        f"<!-- Confidence: {level} | "
        f"Based on {summary.files_analyzed} files, "
        f"{summary.raw_pattern_count} patterns -->"
    )


def _pct(count: int, total: int) -> str:
    """Format a percentage string like '87%'."""
    if total == 0:
        return "0%"
    return f"{count * 100 // total}%"


def _format_evidence_inline(evidence: list[str], max_items: int = 3) -> str:
    """Format evidence as inline backtick list: `a`, `b`, `c`."""
    items = evidence[:max_items]
    return ", ".join(f"`{e}`" for e in items)


def _render_entry(entry: ConventionEntry, bullet: str = "-") -> list[str]:
    """Render a single ConventionEntry as markdown lines."""
    lines: list[str] = []
    pct = _pct(entry.file_count, entry.total_files)
    lines.append(
        f"{bullet} **{pct} {entry.description}** ({entry.file_count}/{entry.total_files} files)"
    )
    if entry.evidence:
        lines.append(f"  - Examples: {_format_evidence_inline(entry.evidence)}")
    if entry.conflict:
        lines.append(f"  - Note: {entry.conflict}")
    return lines


def _render_config_values(config: dict[str, str], prefix: str = "") -> list[str]:
    """Render config values as markdown lines."""
    lines: list[str] = []
    for key, val in sorted(config.items()):
        # Make config key human-readable.
        source = key.split(".")[0] if "." in key else key
        setting = key.split(".", 1)[1] if "." in key else key
        lines.append(f"{prefix}- **Configured in {source}:** {setting} = {val}")
    return lines


# ---------------------------------------------------------------------------
# Category-Specific Renderers (evidence-only)
# ---------------------------------------------------------------------------


def _render_naming(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render naming conventions skill with evidence-only content."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Naming conventions observed in this {langs} project.",
        "",
    ]

    # Group entries by name for subsections.
    by_name = _group_entries_by_name(summary.entries)

    if "function_naming" in by_name:
        lines.append("## Function Naming")
        for entry in by_name["function_naming"]:
            lines.extend(_render_entry(entry))
        lines.append("")

    if "class_naming" in by_name:
        lines.append("## Class Naming")
        for entry in by_name["class_naming"]:
            lines.extend(_render_entry(entry))
        lines.append("")

    # Render any remaining entry groups.
    for name, entries in by_name.items():
        if name in ("function_naming", "class_naming"):
            continue
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    if summary.config_values:
        lines.append("## Tool Configuration")
        lines.extend(_render_config_values(summary.config_values))
        lines.append("")

    return "\n".join(lines)


def _render_error_handling(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render error handling skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Error handling patterns observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _render_testing(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render testing conventions skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Testing conventions observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    # Render in preferred order.
    preferred = [
        "test_framework", "test_file_naming", "assertion_style",
        "pytest_fixtures", "mocking", "parametrized_tests", "table_driven_tests",
    ]
    rendered: set[str] = set()
    for name in preferred:
        if name in by_name:
            heading = name.replace("_", " ").title()
            lines.append(f"## {heading}")
            for entry in by_name[name]:
                lines.extend(_render_entry(entry))
            lines.append("")
            rendered.add(name)

    for name, entries in by_name.items():
        if name in rendered:
            continue
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _render_imports(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render import conventions skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Import and dependency patterns observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    if summary.config_values:
        lines.append("## Tool Configuration")
        lines.extend(_render_config_values(summary.config_values))
        lines.append("")

    return "\n".join(lines)


def _render_documentation(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render documentation conventions skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Documentation patterns observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _render_architecture(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render architecture skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Architecture patterns observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    if "top_level_dirs" in by_name:
        lines.append("## Project Structure")
        for entry in by_name["top_level_dirs"]:
            lines.append(f"- {entry.description}")
            if entry.evidence:
                lines.append("")
                lines.append("```")
                for ev in entry.evidence:
                    lines.append(f"  {ev}")
                lines.append("```")
        lines.append("")

    # Render remaining groups.
    for name, entries in by_name.items():
        if name == "top_level_dirs":
            continue
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _render_style(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render code style skill with config values."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Code style conventions observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    # Render style entries in preferred order.
    preferred = [
        "line_length", "quote_style", "semicolons", "type_hints",
        "trailing_commas", "variable_declaration",
    ]
    rendered: set[str] = set()
    for name in preferred:
        if name in by_name:
            heading = name.replace("_", " ").title()
            lines.append(f"## {heading}")
            for entry in by_name[name]:
                lines.extend(_render_entry(entry))
            # Inject relevant config value if present.
            _inject_related_config(name, summary.config_values, lines)
            lines.append("")
            rendered.add(name)

    for name, entries in by_name.items():
        if name in rendered:
            continue
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    # Formatters and linters from config.
    config = summary.config_values
    if config:
        lines.append("## Formatters & Linters")
        # Ruff
        if any(k.startswith("ruff.") for k in config):
            ruff_details: list[str] = []
            for k, v in sorted(config.items()):
                if k.startswith("ruff."):
                    setting = k.split(".", 1)[1]
                    ruff_details.append(f"{setting}: {v}")
            source = "ruff.toml"
            for f in conventions.config_files_parsed:
                if "ruff" in f.lower():
                    source = f
                    break
            lines.append(f"- **ruff** -- configured in {source}")
            for detail in ruff_details:
                lines.append(f"  - {detail}")

        # Prettier
        if any(k.startswith("prettier.") for k in config):
            prettier_details: list[str] = []
            for k, v in sorted(config.items()):
                if k.startswith("prettier."):
                    setting = k.split(".", 1)[1]
                    prettier_details.append(f"{setting}: {v}")
            lines.append("- **Prettier** -- configured")
            for detail in prettier_details:
                lines.append(f"  - {detail}")

        # ESLint
        if "eslint.config" in config:
            lines.append(f"- **ESLint** -- configured in {config['eslint.config']}")

        # Mypy
        if any(k.startswith("mypy.") for k in config):
            mypy_details: list[str] = []
            for k, v in sorted(config.items()):
                if k.startswith("mypy."):
                    setting = k.split(".", 1)[1]
                    mypy_details.append(f"{setting}: {v}")
            source = "pyproject.toml"
            for f in conventions.config_files_parsed:
                if "mypy" in f.lower():
                    source = f
                    break
            lines.append(f"- **mypy** -- configured in {source}")
            for detail in mypy_details:
                lines.append(f"  - {detail}")

        # golangci-lint
        if any(k.startswith("golangci.") for k in config):
            cfg = config.get("golangci.config", ".golangci.yml")
            lines.append(f"- **golangci-lint** -- configured in {cfg}")
            if "golangci.linters" in config:
                lines.append(f"  - linters: {config['golangci.linters']}")

        lines.append("")

    return "\n".join(lines)


def _render_logging(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render logging and observability skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"Logging and observability patterns observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _render_generic(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Generic renderer for categories without a specific renderer."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        f"# {summary.category.display_name}",
        _confidence_comment(summary),
        "",
        f"{summary.category.description} Observed in this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"## {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _group_entries_by_name(entries: list[ConventionEntry]) -> dict[str, list[ConventionEntry]]:
    """Group convention entries by name, preserving insertion order."""
    by_name: dict[str, list[ConventionEntry]] = {}
    for entry in entries:
        by_name.setdefault(entry.name, []).append(entry)
    return by_name


def _inject_related_config(
    entry_name: str,
    config: dict[str, str],
    lines: list[str],
) -> None:
    """Add relevant config lines after a style entry if applicable."""
    mapping: dict[str, list[str]] = {
        "line_length": ["ruff.line-length", "prettier.printWidth"],
        "quote_style": ["ruff.quote-style", "prettier.singleQuote"],
        "semicolons": ["prettier.semi"],
    }
    keys = mapping.get(entry_name, [])
    for key in keys:
        if key in config:
            source = key.split(".")[0]
            setting = key.split(".", 1)[1]
            lines.append(f"  - **Configured in {source}:** {setting} = {config[key]}")


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
