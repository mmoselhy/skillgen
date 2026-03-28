"""Synthesize raw analysis patterns into deduplicated, stats-enriched conventions."""

from __future__ import annotations

import json
import time
import tomllib
from collections import defaultdict
from pathlib import Path

from skillgen.models import (
    AnalysisResult,
    CategorySummary,
    CodePattern,
    Confidence,
    ConventionEntry,
    Language,
    PatternCategory,
    ProjectConventions,
)


def synthesize(analysis: AnalysisResult) -> ProjectConventions:
    """Transform raw AnalysisResult into deduplicated ProjectConventions.

    Steps:
      1. Deduplicate patterns across files (group by category + name + description).
      2. Compute project-wide prevalence stats.
      3. Parse config files for tool settings.
      4. Filter low-value entries.
      5. Return a complete ProjectConventions object.
    """
    start = time.monotonic()

    # Parse config files first so we can inject them into category summaries.
    config_settings, config_files_parsed = _parse_config_files(analysis.project_info.root_path)

    # Build per-category summaries.
    categories: dict[PatternCategory, CategorySummary] = {}
    for category in PatternCategory:
        category_patterns = analysis.patterns_by_category(category)
        if not category_patterns:
            continue

        raw_count = len(category_patterns)
        entries = _deduplicate_and_merge(category_patterns, analysis.files_analyzed)

        # Filter low-value entries: LOW confidence + <10% prevalence.
        entries = [
            e for e in entries if not (e.confidence == Confidence.LOW and e.prevalence < 0.1)
        ]

        # Sort by prevalence descending.
        entries.sort(key=lambda e: e.prevalence, reverse=True)

        # Determine files_analyzed for this category (unique file paths in patterns).
        cat_files: set[str] = set()
        for p in category_patterns:
            if p.file_path is not None:
                cat_files.add(str(p.file_path))
        files_analyzed_cat = len(cat_files) if cat_files else analysis.files_analyzed

        # Extract relevant config values for this category.
        cat_config = _config_for_category(category, config_settings)

        categories[category] = CategorySummary(
            category=category,
            entries=entries,
            files_analyzed=files_analyzed_cat,
            raw_pattern_count=raw_count,
            config_values=cat_config,
        )

    elapsed = time.monotonic() - start

    return ProjectConventions(
        project_info=analysis.project_info,
        categories=categories,
        config_settings=config_settings,
        config_files_parsed=config_files_parsed,
        files_analyzed=analysis.files_analyzed,
        analysis_duration_seconds=analysis.analysis_duration_seconds,
        synthesis_duration_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Pattern deduplication and merging
# ---------------------------------------------------------------------------


def _deduplicate_and_merge(
    patterns: list[CodePattern],
    total_files_analyzed: int,
) -> list[ConventionEntry]:
    """Group patterns by name, merge into ConventionEntry objects.

    For patterns with the same name, we pick the dominant description (most files),
    merge evidence, and note conflicts. Patterns like "type_hints" that differ only
    in per-file counts are collapsed into one entry.
    """
    by_name: dict[str, list[CodePattern]] = defaultdict(list)
    for p in patterns:
        by_name[p.name].append(p)

    entries: list[ConventionEntry] = []
    # Names that should be fully aggregated (per-file counts differ but concept is the same)
    aggregate_names = {"type_hints", "trailing_commas", "import_volume"}

    for name, group in by_name.items():
        # Count unique files across all variants of this pattern name
        all_files: set[str] = set()
        for p in group:
            if p.file_path is not None:
                all_files.add(str(p.file_path))
        total_files_for_name = len(all_files) if all_files else len(group)
        total_files = max(total_files_analyzed, total_files_for_name)

        if name in aggregate_names:
            # Aggregate mode: collapse all variants into a single entry
            entries.append(_aggregate_pattern_group(name, group, total_files_for_name, total_files))
        else:
            # Variant mode: keep distinct descriptions, note conflicts between them
            entries.extend(_variant_pattern_group(name, group, total_files, total_files_analyzed))

    return entries


def _aggregate_pattern_group(
    name: str,
    group: list[CodePattern],
    file_count: int,
    total_files: int,
) -> ConventionEntry:
    """Collapse all patterns with the same name into one aggregated entry."""
    # Merge evidence
    evidence: list[str] = []
    seen: set[str] = set()
    for p in group:
        for ev in p.evidence:
            if ev not in seen and len(evidence) < 5:
                seen.add(ev)
                evidence.append(ev)

    # Pick highest confidence
    conf_order = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
    best = max(group, key=lambda p: conf_order.get(p.confidence, 0))

    # Build an aggregate description
    desc = group[0].description.split("(")[0].strip() if group else name
    desc = f"{desc} ({file_count} files)"

    # Most common language
    lang = _dominant_language(group)

    return ConventionEntry(
        name=name,
        description=desc,
        prevalence=file_count / total_files if total_files > 0 else 0.0,
        file_count=file_count,
        total_files=total_files,
        confidence=best.confidence,
        evidence=evidence,
        language=lang,
    )


def _variant_pattern_group(
    name: str,
    group: list[CodePattern],
    total_files: int,
    total_files_analyzed: int,
) -> list[ConventionEntry]:
    """Keep distinct description variants, noting conflicts between them."""
    by_desc: dict[str, list[CodePattern]] = defaultdict(list)
    for p in group:
        by_desc[p.description].append(p)

    # Count files per variant
    desc_file_counts: dict[str, int] = {}
    for desc, pats in by_desc.items():
        files: set[str] = set()
        for p in pats:
            if p.file_path is not None:
                files.add(str(p.file_path))
        desc_file_counts[desc] = len(files) if files else len(pats)

    # Only keep variants that appear in >1 file OR are the only variant
    # This filters out one-off anomalies
    if len(by_desc) > 3:
        # Too many variants — keep top 3 by file count
        sorted_descs = sorted(desc_file_counts.items(), key=lambda x: -x[1])[:3]
        keep_descs = {d for d, _ in sorted_descs}
    else:
        keep_descs = set(by_desc.keys())

    entries: list[ConventionEntry] = []
    for desc in keep_descs:
        pats = by_desc[desc]
        file_count = desc_file_counts[desc]
        prevalence = file_count / total_files if total_files > 0 else 0.0

        # Merge evidence
        evidence: list[str] = []
        seen: set[str] = set()
        for p in pats:
            for ev in p.evidence:
                if ev not in seen and len(evidence) < 5:
                    seen.add(ev)
                    evidence.append(ev)

        conf_order = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
        best = max(pats, key=lambda p: conf_order.get(p.confidence, 0))

        # Build conflict note (top 2 competing variants only)
        conflict: str | None = None
        if len(by_desc) > 1:
            others = sorted(
                [(d, c) for d, c in desc_file_counts.items() if d != desc],
                key=lambda x: -x[1],
            )[:2]
            parts = []
            for other_desc, other_count in others:
                pct = other_count / total_files if total_files > 0 else 0
                # Shorten the description for the conflict note
                short = other_desc[:60] + "..." if len(other_desc) > 60 else other_desc
                parts.append(f"{pct:.0%} {short}")
            conflict = "; ".join(parts) if parts else None

        entries.append(
            ConventionEntry(
                name=name,
                description=desc,
                prevalence=prevalence,
                file_count=file_count,
                total_files=total_files,
                confidence=best.confidence,
                evidence=evidence,
                language=_dominant_language(pats),
                conflict=conflict,
            )
        )

    return entries


def _dominant_language(patterns: list[CodePattern]) -> Language | None:
    """Return the most common language among patterns."""
    lang_counts: dict[Language, int] = defaultdict(int)
    for p in patterns:
        if p.language is not None:
            lang_counts[p.language] += 1
    return max(lang_counts, key=lambda lg: lang_counts[lg]) if lang_counts else None


# ---------------------------------------------------------------------------
# Config file parsing
# ---------------------------------------------------------------------------


def _parse_config_files(root: Path) -> tuple[dict[str, str], list[str]]:
    """Parse tool config files and extract settings. Never crashes."""
    settings: dict[str, str] = {}
    parsed_files: list[str] = []

    # --- Ruff (ruff.toml or pyproject.toml [tool.ruff]) ---
    _parse_ruff(root, settings, parsed_files)

    # --- Prettier (.prettierrc or .prettierrc.json) ---
    _parse_prettier(root, settings, parsed_files)

    # --- ESLint ---
    _parse_eslint(root, settings, parsed_files)

    # --- Mypy (mypy.ini or pyproject.toml [tool.mypy]) ---
    _parse_mypy(root, settings, parsed_files)

    # --- golangci-lint ---
    _parse_golangci(root, settings, parsed_files)

    return settings, parsed_files


def _parse_ruff(root: Path, settings: dict[str, str], parsed_files: list[str]) -> None:
    """Parse ruff settings from ruff.toml or pyproject.toml."""
    try:
        ruff_toml = root / "ruff.toml"
        if ruff_toml.is_file():
            data = tomllib.loads(ruff_toml.read_text(encoding="utf-8"))
            parsed_files.append("ruff.toml")
            if "line-length" in data:
                settings["ruff.line-length"] = str(data["line-length"])
            if "quote-style" in data:
                settings["ruff.quote-style"] = str(data["quote-style"])
            lint = data.get("lint", {})
            if "select" in lint:
                settings["ruff.select"] = ", ".join(lint["select"])
            return
    except Exception:
        pass

    try:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            ruff = data.get("tool", {}).get("ruff", {})
            if ruff:
                parsed_files.append("pyproject.toml [tool.ruff]")
                if "line-length" in ruff:
                    settings["ruff.line-length"] = str(ruff["line-length"])
                if "target-version" in ruff:
                    settings["ruff.target-version"] = str(ruff["target-version"])
                lint = ruff.get("lint", {})
                if "select" in lint:
                    settings["ruff.select"] = ", ".join(lint["select"])
    except Exception:
        pass


def _parse_prettier(root: Path, settings: dict[str, str], parsed_files: list[str]) -> None:
    """Parse Prettier settings from .prettierrc or .prettierrc.json."""
    for name in (".prettierrc", ".prettierrc.json"):
        try:
            p = root / name
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                parsed_files.append(name)
                if "singleQuote" in data:
                    settings["prettier.singleQuote"] = str(data["singleQuote"]).lower()
                if "semi" in data:
                    settings["prettier.semi"] = str(data["semi"]).lower()
                if "tabWidth" in data:
                    settings["prettier.tabWidth"] = str(data["tabWidth"])
                if "printWidth" in data:
                    settings["prettier.printWidth"] = str(data["printWidth"])
                return
        except Exception:
            pass


def _parse_eslint(root: Path, settings: dict[str, str], parsed_files: list[str]) -> None:
    """Note presence of ESLint config files."""
    for name in (".eslintrc.json", ".eslintrc.js", ".eslintrc"):
        try:
            p = root / name
            if p.is_file():
                parsed_files.append(name)
                settings["eslint.config"] = name
                return
        except Exception:
            pass


def _parse_mypy(root: Path, settings: dict[str, str], parsed_files: list[str]) -> None:
    """Parse mypy settings from mypy.ini or pyproject.toml."""
    try:
        mypy_ini = root / "mypy.ini"
        if mypy_ini.is_file():
            parsed_files.append("mypy.ini")
            content = mypy_ini.read_text(encoding="utf-8")
            if "strict" in content:
                settings["mypy.strict"] = "true"
            # Simple ini-style parse for python_version.
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("python_version"):
                    parts = stripped.split("=", 1)
                    if len(parts) == 2:
                        settings["mypy.python_version"] = parts[1].strip()
            return
    except Exception:
        pass

    try:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            mypy = data.get("tool", {}).get("mypy", {})
            if mypy:
                parsed_files.append("pyproject.toml [tool.mypy]")
                if mypy.get("strict"):
                    settings["mypy.strict"] = "true"
                if "python_version" in mypy:
                    settings["mypy.python_version"] = str(mypy["python_version"])
    except Exception:
        pass


def _parse_golangci(root: Path, settings: dict[str, str], parsed_files: list[str]) -> None:
    """Note presence and basic settings of golangci-lint."""
    for name in (".golangci.yml", ".golangci.yaml"):
        try:
            p = root / name
            if p.is_file():
                parsed_files.append(name)
                settings["golangci.config"] = name
                # Try to extract enabled linters (YAML parsing with stdlib is limited,
                # so we do a best-effort line scan).
                content = p.read_text(encoding="utf-8")
                linters: list[str] = []
                in_enable = False
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("enable:"):
                        in_enable = True
                        continue
                    if in_enable:
                        if stripped.startswith("- "):
                            linters.append(stripped[2:].strip())
                        else:
                            in_enable = False
                if linters:
                    settings["golangci.linters"] = ", ".join(linters)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_for_category(
    category: PatternCategory, config_settings: dict[str, str]
) -> dict[str, str]:
    """Extract config settings relevant to a specific category."""
    relevant: dict[str, str] = {}
    if category == PatternCategory.STYLE:
        for key, val in config_settings.items():
            relevant[key] = val
    elif category == PatternCategory.NAMING:
        for key, val in config_settings.items():
            if "naming" in key.lower() or key.startswith("ruff.select"):
                relevant[key] = val
    elif category == PatternCategory.IMPORTS:
        for key, val in config_settings.items():
            if "import" in key.lower() or "isort" in key.lower():
                relevant[key] = val
    elif category == PatternCategory.TESTING:
        # No config typically, but keep for extensibility.
        pass
    return relevant
