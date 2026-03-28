"""Fetch community-curated skills from a GitHub-hosted index and apply them locally."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

from skillgen import __version__
from skillgen.models import (
    EnrichmentResult,
    IndexEntry,
    OutputFormat,
    ProjectConventions,
    WrittenFile,
)

logger = logging.getLogger(__name__)

# --- Constants ---

INDEX_URL = "https://raw.githubusercontent.com/mmoselhy/skill-index/main/index.json"
BASE_URL = "https://raw.githubusercontent.com/mmoselhy/skill-index/main/"
CACHE_TTL_SECONDS = 86400
FETCH_TIMEOUT_SECONDS = 10


# --- Caching ---


def _get_cache_dir(cache_dir: Path | None) -> Path:
    """Return the cache directory, defaulting to ~/.cache/skillgen/."""
    if cache_dir is not None:
        return cache_dir
    return Path.home() / ".cache" / "skillgen"


def _write_cache(cache_dir: Path, filename: str, content: str) -> None:
    """Write content to a cache file, creating directories as needed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / filename
    cache_file.write_text(content, encoding="utf-8")


def _read_cache(cache_dir: Path, filename: str, max_age_seconds: int) -> str | None:
    """Read a cache file if it exists and is fresher than max_age_seconds.

    Returns None if the file is missing, unreadable, or stale.
    """
    cache_file = cache_dir / filename
    try:
        if not cache_file.is_file():
            return None
        age = time.time() - cache_file.stat().st_mtime
        if age > max_age_seconds:
            return None
        return cache_file.read_text(encoding="utf-8")
    except OSError:
        return None


# --- Network helpers ---


def _fetch_url(url: str) -> bytes | None:
    """Fetch a URL with a 10-second timeout and User-Agent header.

    Returns the response body as bytes, or None on any failure.
    """
    try:
        request = Request(
            url,
            headers={"User-Agent": f"skillgen/{__version__}"},
        )
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read()  # type: ignore[no-any-return]
    except Exception:
        logger.debug("Failed to fetch %s", url, exc_info=True)
        return None


# --- Index fetching ---


def _parse_index(content: str) -> list[IndexEntry]:
    """Parse index JSON content into IndexEntry objects.

    Skips malformed entries without raising.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.debug("Failed to parse index JSON")
        return []

    # Support both {"skills": [...]} and bare [...] formats
    if isinstance(data, dict):
        items = data.get("skills", [])
    elif isinstance(data, list):
        items = data
    else:
        logger.debug("Index JSON has unexpected type: %s", type(data).__name__)
        return []

    entries: list[IndexEntry] = []
    for item in items:
        try:
            entry = IndexEntry(
                id=str(item["id"]),
                name=str(item["name"]),
                language=str(item["language"]),
                framework=item.get("framework"),
                categories=[str(c) for c in item["categories"]],
                path=str(item["path"]),
                description=str(item.get("description", "")),
            )
            entries.append(entry)
        except (KeyError, TypeError):
            logger.debug("Skipping malformed index entry: %s", item)
            continue

    return entries


def _fetch_index(
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> list[IndexEntry]:
    """Fetch the skill index, using cache when appropriate.

    Strategy:
    1. If cache is fresh and no_cache is False, use cached version.
    2. Otherwise fetch from network.
    3. On network failure, fall back to stale cache.
    4. On all failure, return [].
    """
    resolved_cache_dir = _get_cache_dir(cache_dir)
    cache_filename = "index.json"

    # Try fresh cache first (unless no_cache is set).
    if not no_cache:
        cached = _read_cache(resolved_cache_dir, cache_filename, CACHE_TTL_SECONDS)
        if cached is not None:
            entries = _parse_index(cached)
            if entries:
                return entries

    # Fetch from network.
    raw = _fetch_url(INDEX_URL)
    if raw is not None:
        content = raw.decode("utf-8")
        entries = _parse_index(content)
        if entries:
            _write_cache(resolved_cache_dir, cache_filename, content)
            return entries

    # Fall back to stale cache on network failure.
    if not no_cache:
        try:
            cache_file = resolved_cache_dir / cache_filename
            if cache_file.is_file():
                stale = cache_file.read_text(encoding="utf-8")
                entries = _parse_index(stale)
                if entries:
                    logger.info("Using stale cache for skill index")
                    return entries
        except OSError:
            pass

    return []


# --- Matching ---


def _match_entries(
    entries: list[IndexEntry],
    conventions: ProjectConventions,
) -> tuple[list[IndexEntry], list[str]]:
    """Match index entries against project conventions.

    Matching rules:
    - Language must match (required).
    - Framework must match if set on the entry.
    - Entries whose categories are ALL already covered locally are skipped.

    Returns (matched_entries, skipped_category_names).
    """
    # Gather project languages (lowercase).
    project_languages: set[str] = set()
    for lang_info in conventions.project_info.languages:
        project_languages.add(lang_info.language.value.lower())

    # Gather project frameworks (lowercase).
    project_frameworks: set[str] = set()
    for fw in conventions.project_info.frameworks:
        project_frameworks.add(fw.name.lower())

    # Gather locally-covered categories from conventions.
    local_categories: set[str] = set()
    for cat in conventions.categories:
        local_categories.add(cat.value.lower())

    matched: list[IndexEntry] = []
    skipped: list[str] = []

    for entry in entries:
        # Language must match.
        if entry.language.lower() not in project_languages:
            continue

        # Framework must match if specified on the entry.
        if entry.framework is not None and entry.framework.lower() not in project_frameworks:
            continue

        # Skip entries where ALL categories are already covered locally.
        entry_categories = {c.lower() for c in entry.categories}
        if entry_categories and entry_categories.issubset(local_categories):
            skipped.append(entry.name)
            continue

        matched.append(entry)

    return matched, skipped


def search(
    conventions: ProjectConventions,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> EnrichmentResult:
    """Fetch the skill index and match entries against project conventions."""
    errors: list[str] = []

    entries = _fetch_index(cache_dir=cache_dir, no_cache=no_cache)
    if not entries:
        errors.append("Could not fetch or parse the skill index.")
        return EnrichmentResult(matched=[], skipped_categories=[], errors=errors)

    matched, skipped = _match_entries(entries, conventions)
    return EnrichmentResult(matched=matched, skipped_categories=skipped, errors=errors)


# --- Download and apply ---


def _fetch_skill_content(
    path: str,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> str | None:
    """Fetch a single skill markdown file from the index repository.

    Returns the file content as a string, or None on failure.
    """
    resolved_cache_dir = _get_cache_dir(cache_dir)
    cache_filename = path.replace("/", "_")

    # Try fresh cache.
    if not no_cache:
        cached = _read_cache(resolved_cache_dir, cache_filename, CACHE_TTL_SECONDS)
        if cached is not None:
            return cached

    # Fetch from network.
    url = BASE_URL + path
    raw = _fetch_url(url)
    if raw is not None:
        content = raw.decode("utf-8")
        _write_cache(resolved_cache_dir, cache_filename, content)
        return content

    return None


def _slugify(name: str) -> str:
    """Convert a skill name to a filename-safe slug.

    Example: "Pytest Patterns" -> "pytest-patterns"
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def _format_community_claude(entry: IndexEntry, content: str) -> str:
    """Format a community skill for .claude/skills/community/*.md."""
    lines = [
        f"<!-- Community skill: {entry.name} (id: {entry.id}) -->",
        f"<!-- Source: {BASE_URL}{entry.path} -->",
        "",
        content,
    ]
    return "\n".join(lines)


def _format_community_cursor(entry: IndexEntry, content: str) -> str:
    """Format a community skill for .cursor/rules/community/*.mdc."""
    lines = [
        "---",
        f"description: {entry.description}",
        "globs: *",
        "alwaysApply: false",
        "---",
        "",
        f"<!-- Community skill: {entry.name} (id: {entry.id}) -->",
        f"<!-- Source: {BASE_URL}{entry.path} -->",
        "",
        content,
    ]
    return "\n".join(lines)


def apply(
    entries: list[IndexEntry],
    target_dir: Path,
    output_format: OutputFormat,
    pick: list[str] | None = None,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> list[WrittenFile]:
    """Download and write selected community skills to disk.

    Args:
        entries: Index entries to apply.
        target_dir: Project root directory.
        output_format: Which format(s) to write.
        pick: Optional list of entry IDs to filter to.
        cache_dir: Optional cache directory override.
        no_cache: If True, bypass cache.

    Returns:
        List of WrittenFile records for files successfully written.
    """
    # Filter by pick list if provided.
    if pick is not None:
        pick_set = set(pick)
        entries = [e for e in entries if e.id in pick_set]

    written: list[WrittenFile] = []

    for entry in entries:
        content = _fetch_skill_content(entry.path, cache_dir=cache_dir, no_cache=no_cache)
        if content is None:
            logger.warning("Failed to download skill: %s", entry.name)
            continue

        slug = _slugify(entry.name)

        if output_format in (OutputFormat.CLAUDE, OutputFormat.ALL):
            claude_dir = target_dir / ".claude" / "skills" / "community"
            claude_dir.mkdir(parents=True, exist_ok=True)
            claude_path = claude_dir / f"{slug}.md"
            claude_content = _format_community_claude(entry, content)
            claude_path.write_text(claude_content, encoding="utf-8")
            written.append(
                WrittenFile(
                    path=claude_path,
                    format="claude",
                    line_count=claude_content.count("\n") + 1,
                )
            )

        if output_format in (OutputFormat.CURSOR, OutputFormat.ALL):
            cursor_dir = target_dir / ".cursor" / "rules" / "community"
            cursor_dir.mkdir(parents=True, exist_ok=True)
            cursor_path = cursor_dir / f"{slug}.mdc"
            cursor_content = _format_community_cursor(entry, content)
            cursor_path.write_text(cursor_content, encoding="utf-8")
            written.append(
                WrittenFile(
                    path=cursor_path,
                    format="cursor",
                    line_count=cursor_content.count("\n") + 1,
                )
            )

    return written
