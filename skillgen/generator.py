"""Skill content generation: evidence-only renderers backed by ProjectConventions."""

from __future__ import annotations

import enum
import os
import re
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


def _to_imperative(description: str) -> str:
    """Convert a descriptive observation to an imperative rule.

    'Functions use snake_case' -> 'Use snake_case for all functions'
    'Classes use PascalCase' -> 'Use PascalCase for all classes'
    'Uses try/except with ValueError' -> 'Use try/except with ValueError'
    'Module docstrings present' -> 'Include module docstrings'
    """
    desc = description.strip()

    # Common transformations
    replacements = [
        # "Functions use snake_case" -> "Use snake_case for functions"
        (r"^(\w+(?:\s+\w+)*?)\s+use\s+(.+)$", r"Use \2 for \1"),
        # "Uses X" -> "Use X"
        (r"^Uses\s+(.+)$", r"Use \1"),
        # "X present" -> "Include X"
        (r"^(.+?)\s+present$", r"Include \1"),
        # "Has X" -> "Include X"
        (r"^Has\s+(.+)$", r"Include \1"),
        # "Prefers X" -> "Use X"
        (r"^Prefers?\s+(.+)$", r"Use \1"),
    ]

    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, desc, flags=re.IGNORECASE)
        if result != desc:
            # Ensure first letter is capitalized
            return result[0].upper() + result[1:]

    # If no pattern matched, just ensure it starts with a verb
    # If it already starts with a verb-like word, return as-is
    if desc[0].isupper():
        return desc
    return desc[0].upper() + desc[1:]


def _render_entry(entry: ConventionEntry, bullet: str = "-") -> list[str]:
    """Render a single ConventionEntry as an imperative rule."""
    lines: list[str] = []
    imperative = _to_imperative(entry.description)
    lines.append(f"{bullet} **{imperative}**")
    if entry.evidence:
        lines.append(f"  - Examples: {_format_evidence_inline(entry.evidence)}")
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
        _confidence_comment(summary),
        "",
        f"Follow these naming conventions for this {langs} project.",
        "",
    ]

    # Group entries by name for subsections.
    by_name = _group_entries_by_name(summary.entries)

    if "function_naming" in by_name:
        lines.append("### Function Naming")
        for entry in by_name["function_naming"]:
            lines.extend(_render_entry(entry))
        lines.append("")

    if "class_naming" in by_name:
        lines.append("### Class Naming")
        for entry in by_name["class_naming"]:
            lines.extend(_render_entry(entry))
        lines.append("")

    # Render any remaining entry groups.
    for name, entries in by_name.items():
        if name in ("function_naming", "class_naming"):
            continue
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    if summary.config_values:
        lines.append("### Tool Configuration")
        lines.extend(_render_config_values(summary.config_values))
        lines.append("")

    _maybe_append_snippet(lines, summary)
    return "\n".join(lines)


def _render_error_handling(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render error handling skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"Follow these error handling patterns for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    _maybe_append_snippet(lines, summary)
    return "\n".join(lines)


def _render_testing(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render testing conventions skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"Follow these testing conventions for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    # Render in preferred order.
    preferred = [
        "test_framework",
        "test_file_naming",
        "assertion_style",
        "pytest_fixtures",
        "mocking",
        "parametrized_tests",
        "table_driven_tests",
    ]
    rendered: set[str] = set()
    for name in preferred:
        if name in by_name:
            heading = name.replace("_", " ").title()
            lines.append(f"### {heading}")
            for entry in by_name[name]:
                lines.extend(_render_entry(entry))
            lines.append("")
            rendered.add(name)

    for name, entries in by_name.items():
        if name in rendered:
            continue
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    _maybe_append_snippet(lines, summary)
    return "\n".join(lines)


def _render_imports(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render import conventions skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"Follow these import and dependency patterns for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    if summary.config_values:
        lines.append("### Tool Configuration")
        lines.extend(_render_config_values(summary.config_values))
        lines.append("")

    _maybe_append_snippet(lines, summary)
    return "\n".join(lines)


def _render_documentation(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render documentation conventions skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"Follow these documentation patterns for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    _maybe_append_snippet(lines, summary)
    return "\n".join(lines)


def _render_architecture(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render architecture skill."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"Follow these architecture patterns for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    if "top_level_dirs" in by_name:
        lines.append("### Project Structure")
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
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _render_style(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Render code style skill with config values."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"Follow these code style conventions for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)

    # Render style entries in preferred order.
    preferred = [
        "line_length",
        "quote_style",
        "semicolons",
        "type_hints",
        "trailing_commas",
        "variable_declaration",
    ]
    rendered: set[str] = set()
    for name in preferred:
        if name in by_name:
            heading = name.replace("_", " ").title()
            lines.append(f"### {heading}")
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
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    # Formatters and linters from config.
    config = summary.config_values
    if config:
        lines.append("### Formatters & Linters")
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
        _confidence_comment(summary),
        "",
        f"Follow these logging and observability patterns for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    _maybe_append_snippet(lines, summary)
    return "\n".join(lines)


def _render_generic(summary: CategorySummary, conventions: ProjectConventions) -> str:
    """Generic renderer for categories without a specific renderer."""
    langs = ", ".join(conventions.project_info.language_names)
    lines: list[str] = [
        _confidence_comment(summary),
        "",
        f"{summary.category.description} Follow these conventions for this {langs} project.",
        "",
    ]

    by_name = _group_entries_by_name(summary.entries)
    for name, entries in by_name.items():
        heading = name.replace("_", " ").title()
        lines.append(f"### {heading}")
        for entry in entries:
            lines.extend(_render_entry(entry))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Code Snippet Builders
# ---------------------------------------------------------------------------

# Maps Language enum values to markdown code fence language identifiers.
_LANG_FENCE: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "javascript": "javascript",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "cpp": "cpp",
}


def _fence_lang(summary: CategorySummary) -> str:
    """Determine the code fence language from a category summary's entries."""
    for entry in summary.entries:
        if entry.language is not None:
            return _LANG_FENCE.get(entry.language.value, "")
    return ""


def _clean_evidence(evidence: str) -> str:
    """Strip file references from evidence strings.

    'analyze_project (analyzer.py)' -> 'analyze_project'
    'class Language (models.py)' -> 'Language'
    """
    # Remove trailing " (filename.ext)" pattern
    cleaned = re.sub(r"\s*\([^)]*\.[a-z]+\)$", "", evidence)
    # Remove leading "class " or "raise " prefixes for use in code
    cleaned = re.sub(r"^(class|raise|import)\s+", "", cleaned)
    return cleaned.strip()


def _snippet_naming(summary: CategorySummary) -> list[str]:
    """Build a naming conventions code snippet from entry evidence."""
    by_name = _group_entries_by_name(summary.entries)
    lang = _fence_lang(summary)

    func_names: list[str] = []
    class_names: list[str] = []
    for entry in by_name.get("function_naming", []):
        func_names.extend(_clean_evidence(e) for e in entry.evidence[:2])
    for entry in by_name.get("class_naming", []):
        class_names.extend(_clean_evidence(e) for e in entry.evidence[:2])

    if not func_names and not class_names:
        return []

    lines: list[str] = ["### Example", "", f"```{lang}"]

    if lang == "python":
        if class_names:
            cls = class_names[0].replace("class ", "")
            lines.append(f"class {cls}:")
            lines.append(f'    """A {cls} instance."""')
            lines.append("")
        if func_names:
            fn = func_names[0]
            lines.append(f"def {fn}(data: dict) -> None:")
            lines.append('    """Process data."""')
            lines.append("    ...")
    elif lang in ("typescript", "javascript"):
        if class_names:
            cls = class_names[0].replace("class ", "")
            lines.append(f"class {cls} {{")
            lines.append("  constructor() {}")
            lines.append("}")
            lines.append("")
        if func_names:
            fn = func_names[0]
            prefix = "function " if lang == "javascript" else "export function "
            sig = (
                f"{prefix}{fn}(data: Record<string, unknown>): void"
                if lang == "typescript"
                else f"{prefix}{fn}(data)"
            )
            lines.append(f"{sig} {{")
            lines.append("  // ...")
            lines.append("}")
    elif lang == "go":
        if func_names:
            fn = func_names[0]
            lines.append(f"func {fn}(data map[string]any) error {{")
            lines.append("	// ...")
            lines.append("	return nil")
            lines.append("}")
    elif lang == "rust":
        if func_names:
            fn = func_names[0]
            lines.append(f"fn {fn}(data: &Data) -> Result<(), Error> {{")
            lines.append("    // ...")
            lines.append("    Ok(())")
            lines.append("}")
    elif lang == "java":
        if class_names:
            cls = class_names[0].replace("class ", "")
            lines.append(f"public class {cls} {{")
            if func_names:
                fn = func_names[0]
                lines.append(f"    public void {fn}() {{")
                lines.append("        // ...")
                lines.append("    }")
            lines.append("}")
    else:
        # Generic fallback
        if func_names:
            lines.append(f"// {func_names[0]}(...)")
        return []

    lines.extend(["```", ""])
    return lines


def _snippet_error_handling(summary: CategorySummary) -> list[str]:
    """Build an error handling code snippet."""
    by_name = _group_entries_by_name(summary.entries)
    lang = _fence_lang(summary)

    # Collect exception/error type evidence
    exc_types: list[str] = []
    for entry in by_name.get("exception_types", []) + by_name.get("error_types", []):
        exc_types.extend(entry.evidence[:2])

    if not exc_types and not by_name:
        return []

    lines: list[str] = ["### Example", "", f"```{lang}"]

    if lang == "python":
        exc = "ValueError"
        for e in exc_types:
            cleaned = _clean_evidence(e)
            for token in cleaned.split():
                if token and token[0].isupper():
                    exc = token.rstrip("()")
                    break
            break
        lines.append("try:")
        lines.append("    result = process(data)")
        lines.append(f"except {exc} as exc:")
        lines.append('    logger.error("Processing failed", exc_info=exc)')
        lines.append("    raise")
    elif lang in ("typescript", "javascript"):
        lines.append("try {")
        lines.append("  const result = await process(data);")
        lines.append("} catch (error) {")
        lines.append("  logger.error('Processing failed', { error });")
        lines.append("  throw error;")
        lines.append("}")
    elif lang == "go":
        lines.append("result, err := process(data)")
        lines.append("if err != nil {")
        lines.append('    return fmt.Errorf("processing failed: %w", err)')
        lines.append("}")
    elif lang == "rust":
        lines.append("let result = process(data)")
        lines.append('    .map_err(|e| anyhow!("processing failed: {e}"))?;')
    elif lang == "java":
        exc = "Exception"
        for e in exc_types:
            cleaned = _clean_evidence(e).replace("catch (", "").replace(")", "")
            for token in cleaned.split():
                if token and token[0].isupper():
                    exc = token
                    break
            break
        lines.append("try {")
        lines.append("    var result = process(data);")
        lines.append(f"}} catch ({exc} e) {{")
        lines.append('    logger.error("Processing failed", e);')
        lines.append("    throw e;")
        lines.append("}")
    else:
        return []

    lines.extend(["```", ""])
    return lines


def _snippet_testing(summary: CategorySummary) -> list[str]:
    """Build a testing code snippet."""
    by_name = _group_entries_by_name(summary.entries)
    lang = _fence_lang(summary)

    if not by_name:
        return []

    lines: list[str] = ["### Example", "", f"```{lang}"]

    has_pytest = any("pytest" in e.description.lower() for e in summary.entries)
    has_jest = any(
        "jest" in e.description.lower() or "describe" in str(e.evidence) for e in summary.entries
    )
    has_go_test = any("testing.T" in str(e.evidence) for e in summary.entries)
    has_rust_test = any("#[test]" in str(e.evidence) for e in summary.entries)

    if lang == "python" and has_pytest:
        has_fixtures = "pytest_fixtures" in by_name
        if has_fixtures:
            lines.append("@pytest.fixture")
            lines.append("def sample_data():")
            lines.append('    return {"key": "value"}')
            lines.append("")
            lines.append("")
        lines.append(
            "def test_process_returns_expected(sample_data):"
            if has_fixtures
            else "def test_process_returns_expected():"
        )
        lines.append(
            "    result = process(sample_data)"
            if has_fixtures
            else '    result = process({"key": "value"})'
        )
        lines.append("    assert result is not None")
        lines.append('    assert result["status"] == "ok"')
    elif lang == "python":
        lines.append("class TestProcess(unittest.TestCase):")
        lines.append("    def test_returns_expected(self):")
        lines.append('        result = process({"key": "value"})')
        lines.append("        self.assertIsNotNone(result)")
    elif lang in ("typescript", "javascript") and has_jest:
        lines.append("describe('process', () => {")
        lines.append("  it('returns expected result', async () => {")
        lines.append("    const result = await process({ key: 'value' });")
        lines.append("    expect(result).toBeDefined();")
        lines.append("    expect(result.status).toBe('ok');")
        lines.append("  });")
        lines.append("});")
    elif lang == "go" and has_go_test:
        has_table = "table_driven_tests" in by_name
        if has_table:
            lines.append("func TestProcess(t *testing.T) {")
            lines.append("	tests := []struct {")
            lines.append("		name  string")
            lines.append("		input string")
            lines.append("		want  string")
            lines.append("	}{")
            lines.append('		{"valid input", "hello", "HELLO"},')
            lines.append("	}")
            lines.append("	for _, tt := range tests {")
            lines.append("		t.Run(tt.name, func(t *testing.T) {")
            lines.append("			got := process(tt.input)")
            lines.append("			assert.Equal(t, tt.want, got)")
            lines.append("		})")
            lines.append("	}")
            lines.append("}")
        else:
            lines.append("func TestProcess(t *testing.T) {")
            lines.append('	got := process("hello")')
            lines.append('	assert.Equal(t, "HELLO", got)')
            lines.append("}")
    elif lang == "rust" and has_rust_test:
        lines.append("#[cfg(test)]")
        lines.append("mod tests {")
        lines.append("    use super::*;")
        lines.append("")
        lines.append("    #[test]")
        lines.append("    fn test_process() {")
        lines.append('        let result = process("hello");')
        lines.append('        assert_eq!(result, "HELLO");')
        lines.append("    }")
        lines.append("}")
    else:
        return []

    lines.extend(["```", ""])
    return lines


def _snippet_imports(summary: CategorySummary) -> list[str]:
    """Build an import ordering code snippet."""
    by_name = _group_entries_by_name(summary.entries)
    lang = _fence_lang(summary)

    if not by_name:
        return []

    lines: list[str] = ["### Example", "", f"```{lang}"]

    if lang == "python":
        lines.append("import os                          # stdlib")
        lines.append("from pathlib import Path")
        lines.append("")
        lines.append("import requests                    # third-party")
        lines.append("")
        lines.append("from myproject.models import User  # local")
    elif lang in ("typescript", "javascript"):
        lines.append("// third-party")
        lines.append("import express from 'express';")
        lines.append("")
        lines.append("// local")
        lines.append("import { User } from './models';")
        lines.append("import { validate } from '../utils';")
    elif lang == "go":
        lines.append("import (")
        lines.append('	"fmt"')
        lines.append('	"os"')
        lines.append("")
        lines.append('	"github.com/example/pkg"')
        lines.append("")
        lines.append('	"myproject/internal/models"')
        lines.append(")")
    else:
        return []

    lines.extend(["```", ""])
    return lines


def _snippet_documentation(summary: CategorySummary) -> list[str]:
    """Build a documentation style code snippet."""
    by_name = _group_entries_by_name(summary.entries)
    lang = _fence_lang(summary)

    if not by_name:
        return []

    # Detect docstring style from evidence
    has_google = any(
        "google" in str(e.evidence).lower() or "Args:" in str(e.evidence) for e in summary.entries
    )
    has_jsdoc = any(
        "jsdoc" in str(e.evidence).lower() or "@param" in str(e.evidence) for e in summary.entries
    )

    lines: list[str] = ["### Example", "", f"```{lang}"]

    if lang == "python":
        lines.append('"""Module for processing data."""')
        lines.append("")
        lines.append("")
        lines.append("def process(data: dict, strict: bool = False) -> str:")
        if has_google:
            lines.append('    """Process the input data and return a result.')
            lines.append("")
            lines.append("    Args:")
            lines.append("        data: The input data to process.")
            lines.append("        strict: Whether to use strict validation.")
            lines.append("")
            lines.append("    Returns:")
            lines.append("        The processed result string.")
            lines.append('    """')
        else:
            lines.append('    """Process the input data and return a result."""')
    elif lang in ("typescript", "javascript") and has_jsdoc:
        lines.append("/**")
        lines.append(" * Process the input data and return a result.")
        lines.append(" * @param data - The input data to process.")
        lines.append(" * @param strict - Whether to use strict validation.")
        lines.append(" * @returns The processed result string.")
        lines.append(" */")
        lines.append(
            "export function process(data: Record<string, unknown>, strict = false): string {"
            if lang == "typescript"
            else "function process(data, strict = false) {"
        )
        lines.append("  // ...")
        lines.append("}")
    elif lang == "go":
        lines.append("// Process processes the input data and returns a result.")
        lines.append("// It returns an error if the data is invalid.")
        lines.append("func Process(data map[string]any) (string, error) {")
        lines.append("	// ...")
        lines.append("	return result, nil")
        lines.append("}")
    else:
        return []

    lines.extend(["```", ""])
    return lines


def _snippet_logging(summary: CategorySummary) -> list[str]:
    """Build a logging code snippet."""
    lang = _fence_lang(summary)

    # Detect logging library from entries
    has_structlog = any("structlog" in str(e.evidence) for e in summary.entries)
    has_stdlib = any(
        "logging" in str(e.evidence) and "structlog" not in str(e.evidence) for e in summary.entries
    )
    has_zerolog = any("zerolog" in str(e.evidence) for e in summary.entries)
    has_zap = any("zap" in str(e.evidence) for e in summary.entries)

    if not summary.entries:
        return []

    lines: list[str] = ["### Example", "", f"```{lang}"]

    if lang == "python" and has_structlog:
        lines.append("import structlog")
        lines.append("")
        lines.append("logger = structlog.get_logger()")
        lines.append("")
        lines.append('logger.info("processing started", user_id=user_id, count=len(items))')
        lines.append('logger.error("processing failed", error=str(exc), user_id=user_id)')
    elif lang == "python" and has_stdlib:
        lines.append("import logging")
        lines.append("")
        lines.append("logger = logging.getLogger(__name__)")
        lines.append("")
        lines.append('logger.info("Processing started for %s", user_id)')
        lines.append('logger.error("Processing failed: %s", exc, exc_info=True)')
    elif lang in ("typescript", "javascript"):
        lines.append("import { logger } from './logger';")
        lines.append("")
        lines.append("logger.info('Processing started', { userId, count: items.length });")
        lines.append("logger.error('Processing failed', { error: err.message, userId });")
    elif lang == "go" and has_zerolog:
        lines.append(
            'log.Info().Str("user_id", userID).Int("count", len(items)).Msg("processing started")'
        )
        lines.append('log.Error().Err(err).Str("user_id", userID).Msg("processing failed")')
    elif lang == "go" and has_zap:
        lines.append(
            'logger.Info("processing started", zap.String("user_id", userID), zap.Int("count", len(items)))'
        )
        lines.append(
            'logger.Error("processing failed", zap.Error(err), zap.String("user_id", userID))'
        )
    elif lang == "go":
        lines.append('log.Printf("processing started for user %s", userID)')
        lines.append('log.Printf("processing failed: %v", err)')
    else:
        return []

    lines.extend(["```", ""])
    return lines


# Snippet builder per category. Returns empty list if no snippet can be built.
_SNIPPET_BUILDERS: dict[PatternCategory, Callable[[CategorySummary], list[str]]] = {
    PatternCategory.NAMING: _snippet_naming,
    PatternCategory.ERROR_HANDLING: _snippet_error_handling,
    PatternCategory.TESTING: _snippet_testing,
    PatternCategory.IMPORTS: _snippet_imports,
    PatternCategory.DOCUMENTATION: _snippet_documentation,
    PatternCategory.LOGGING: _snippet_logging,
    # ARCHITECTURE already has directory tree code blocks
    # STYLE is config-driven, not code-snippet driven
}


def _maybe_append_snippet(
    lines: list[str],
    summary: CategorySummary,
) -> None:
    """Append a code snippet to the rendered lines if one can be built."""
    builder = _SNIPPET_BUILDERS.get(summary.category)
    if builder is None:
        return
    snippet_lines = builder(summary)
    if snippet_lines:
        lines.extend(snippet_lines)


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
