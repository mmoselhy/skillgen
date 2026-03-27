# Online Skill Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--enrich` and `--enrich --apply` flags that fetch community-curated skills from a GitHub-hosted index, preview them, and optionally install them into the project.

**Architecture:** New `enricher.py` module handles index fetching, matching, caching, and file downloads using only stdlib (`urllib.request`, `json`). Integrates between the synthesize and generate steps in the CLI pipeline. Community skills are written to a `community/` subdirectory under `.claude/skills/` and `.cursor/rules/`.

**Tech Stack:** Python 3.11+ stdlib only (urllib.request, json, pathlib). Rich for terminal output. unittest.mock for network mocking in tests.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `skillgen/enricher.py` | Create | Index fetching, matching, caching, downloading, applying |
| `skillgen/models.py` | Modify | Add `IndexEntry`, `EnrichmentResult` dataclasses |
| `skillgen/cli.py` | Modify | Add `--enrich`, `--apply`, `--pick`, `--no-cache` flags and pipeline integration |
| `skillgen/renderer.py` | Modify | Add `render_enrich_preview()` and `render_enrich_applied()` |
| `tests/test_enricher.py` | Create | All enricher tests (unit + integration, all mocked) |

---

### Task 1: Add Data Models

**Files:**
- Modify: `skillgen/models.py` (append after `ProjectConventions`)

- [ ] **Step 1: Add IndexEntry and EnrichmentResult dataclasses**

Add to the end of `skillgen/models.py`:

```python
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


@dataclass
class EnrichmentResult:
    """Result of searching the online skill index."""

    matched: list[IndexEntry]
    skipped_categories: list[str]
    errors: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Run type check**

Run: `mypy skillgen/models.py --ignore-missing-imports`
Expected: `Success: no issues found`

- [ ] **Step 3: Commit**

```bash
git add skillgen/models.py
git commit -m "feat(models): add IndexEntry and EnrichmentResult for enrichment"
```

---

### Task 2: Implement Enricher Core — Index Fetching and Caching

**Files:**
- Create: `skillgen/enricher.py`
- Create: `tests/test_enricher.py`

- [ ] **Step 1: Write failing tests for index fetching and caching**

Create `tests/test_enricher.py`:

```python
"""Tests for the online skill enricher. All network calls are mocked."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skillgen.enricher import (
    INDEX_URL,
    _fetch_index,
    _get_cache_dir,
    _read_cache,
    _write_cache,
)


class TestCaching:
    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        _write_cache(cache_dir, "index.json", '{"version": 1, "skills": []}')
        content = _read_cache(cache_dir, "index.json", max_age_seconds=3600)
        assert content is not None
        assert '"version": 1' in content

    def test_expired_cache_returns_none(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        _write_cache(cache_dir, "index.json", '{"version": 1}')
        # Read with 0 second TTL — everything is expired
        content = _read_cache(cache_dir, "index.json", max_age_seconds=0)
        assert content is None

    def test_missing_cache_returns_none(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        content = _read_cache(cache_dir, "nonexistent.json", max_age_seconds=3600)
        assert content is None

    def test_get_cache_dir_default(self) -> None:
        cache_dir = _get_cache_dir(None)
        assert "skillgen" in str(cache_dir)


class TestFetchIndex:
    def test_fetch_from_network(self, tmp_path: Path) -> None:
        index_data = json.dumps({
            "version": 1,
            "skills": [
                {
                    "id": "python-pytest",
                    "name": "Pytest",
                    "language": "python",
                    "framework": None,
                    "categories": ["testing"],
                    "path": "skills/python/pytest.md",
                    "description": "Pytest patterns",
                }
            ],
        })
        mock_response = MagicMock()
        mock_response.read.return_value = index_data.encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("skillgen.enricher.urlopen", return_value=mock_response):
            entries = _fetch_index(cache_dir=tmp_path, no_cache=True)

        assert len(entries) == 1
        assert entries[0].id == "python-pytest"

    def test_fetch_uses_cache_when_fresh(self, tmp_path: Path) -> None:
        index_data = json.dumps({
            "version": 1,
            "skills": [
                {
                    "id": "cached-skill",
                    "name": "Cached",
                    "language": "python",
                    "framework": None,
                    "categories": ["testing"],
                    "path": "skills/python/cached.md",
                    "description": "From cache",
                }
            ],
        })
        _write_cache(tmp_path, "index.json", index_data)

        # Should NOT call urlopen — cache is fresh
        with patch("skillgen.enricher.urlopen") as mock_urlopen:
            entries = _fetch_index(cache_dir=tmp_path, no_cache=False)

        mock_urlopen.assert_not_called()
        assert len(entries) == 1
        assert entries[0].id == "cached-skill"

    def test_fetch_network_failure_returns_empty(self, tmp_path: Path) -> None:
        with patch("skillgen.enricher.urlopen", side_effect=OSError("no network")):
            entries = _fetch_index(cache_dir=tmp_path, no_cache=True)

        assert entries == []

    def test_fetch_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json!!"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("skillgen.enricher.urlopen", return_value=mock_response):
            entries = _fetch_index(cache_dir=tmp_path, no_cache=True)

        assert entries == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_enricher.py -v`
Expected: FAIL — `ImportError: cannot import name '_fetch_index' from 'skillgen.enricher'`

- [ ] **Step 3: Implement enricher core (fetching + caching)**

Create `skillgen/enricher.py`:

```python
"""Online skill enrichment: fetch community skills from a GitHub-hosted index."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.request import Request, urlopen

from skillgen import __version__
from skillgen.models import IndexEntry

logger = logging.getLogger(__name__)

INDEX_URL = "https://raw.githubusercontent.com/skillgen/skill-index/main/index.json"
BASE_URL = "https://raw.githubusercontent.com/skillgen/skill-index/main/"
CACHE_TTL_SECONDS = 86400  # 24 hours
FETCH_TIMEOUT_SECONDS = 10


def _get_cache_dir(cache_dir: Path | None) -> Path:
    """Return the cache directory, creating it if needed."""
    if cache_dir is not None:
        return cache_dir
    default = Path.home() / ".cache" / "skillgen"
    default.mkdir(parents=True, exist_ok=True)
    return default


def _write_cache(cache_dir: Path, filename: str, content: str) -> None:
    """Write content to a cache file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / filename).write_text(content, encoding="utf-8")


def _read_cache(cache_dir: Path, filename: str, max_age_seconds: int) -> str | None:
    """Read a cached file if it exists and is within max_age_seconds. Returns None if stale/missing."""
    path = cache_dir / filename
    if not path.is_file():
        return None
    age = time.time() - path.stat().st_mtime
    if age > max_age_seconds:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _fetch_url(url: str) -> bytes | None:
    """Fetch a URL with timeout and user-agent. Returns None on any failure."""
    try:
        req = Request(url, headers={"User-Agent": f"skillgen/{__version__}"})
        with urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            return resp.read()
    except Exception:
        logger.debug("Failed to fetch %s", url)
        return None


def _fetch_index(
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> list[IndexEntry]:
    """Fetch and parse the skill index. Returns empty list on any failure."""
    cache = _get_cache_dir(cache_dir)

    # Try cache first
    if not no_cache:
        cached = _read_cache(cache, "index.json", CACHE_TTL_SECONDS)
        if cached is not None:
            return _parse_index(cached)

    # Fetch from network
    raw = _fetch_url(INDEX_URL)
    if raw is None:
        # Fall back to stale cache
        stale = _read_cache(cache, "index.json", max_age_seconds=999_999_999)
        if stale is not None:
            logger.debug("Using stale cache as fallback")
            return _parse_index(stale)
        return []

    content = raw.decode("utf-8", errors="replace")
    _write_cache(cache, "index.json", content)
    return _parse_index(content)


def _parse_index(content: str) -> list[IndexEntry]:
    """Parse index JSON into IndexEntry list. Returns empty list on parse failure."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Skill index JSON is malformed")
        return []

    if not isinstance(data, dict) or "skills" not in data:
        return []

    entries: list[IndexEntry] = []
    for item in data["skills"]:
        try:
            entries.append(
                IndexEntry(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    language=str(item["language"]),
                    framework=item.get("framework"),
                    categories=list(item.get("categories", [])),
                    path=str(item["path"]),
                    description=str(item.get("description", "")),
                )
            )
        except (KeyError, TypeError):
            logger.debug("Skipping malformed index entry: %s", item)
            continue

    return entries
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_enricher.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Lint and type check**

Run: `ruff check skillgen/enricher.py tests/test_enricher.py && mypy skillgen/enricher.py --ignore-missing-imports`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add skillgen/enricher.py tests/test_enricher.py
git commit -m "feat(enricher): add index fetching with caching and error handling"
```

---

### Task 3: Implement Matching Logic

**Files:**
- Modify: `skillgen/enricher.py`
- Modify: `tests/test_enricher.py`

- [ ] **Step 1: Write failing tests for matching**

Append to `tests/test_enricher.py`:

```python
from skillgen.enricher import _match_entries, search
from skillgen.models import (
    CategorySummary,
    Confidence,
    ConventionEntry,
    EnrichmentResult,
    FrameworkInfo,
    Language,
    LanguageInfo,
    OutputFormat,
    PatternCategory,
    ProjectConventions,
    ProjectInfo,
)


def _make_conventions(
    languages: list[str],
    frameworks: list[str] | None = None,
    covered_categories: list[PatternCategory] | None = None,
) -> ProjectConventions:
    """Build a minimal ProjectConventions for testing matching logic."""
    lang_infos = [
        LanguageInfo(language=Language(l), file_count=10, percentage=50.0)
        for l in languages
    ]
    fw_infos = [
        FrameworkInfo(name=f, language=Language(languages[0]), evidence="detected")
        for f in (frameworks or [])
    ]
    categories: dict[PatternCategory, CategorySummary] = {}
    for cat in (covered_categories or []):
        categories[cat] = CategorySummary(
            category=cat,
            entries=[
                ConventionEntry(
                    name="dummy",
                    description="dummy",
                    prevalence=0.8,
                    file_count=8,
                    total_files=10,
                    confidence=Confidence.HIGH,
                    evidence=["example"],
                )
            ],
            files_analyzed=10,
            raw_pattern_count=5,
        )

    return ProjectConventions(
        project_info=ProjectInfo(
            root_path=Path("/fake"),
            languages=lang_infos,
            frameworks=fw_infos,
            total_files=50,
            source_files=20,
        ),
        categories=categories,
        config_settings={},
        config_files_parsed=[],
        files_analyzed=10,
        analysis_duration_seconds=0.1,
    )


_SAMPLE_ENTRIES = [
    IndexEntry(
        id="python-fastapi",
        name="FastAPI Conventions",
        language="python",
        framework="FastAPI",
        categories=["error-handling", "testing"],
        path="skills/python/fastapi.md",
        description="FastAPI patterns",
    ),
    IndexEntry(
        id="python-pytest",
        name="Pytest Patterns",
        language="python",
        framework=None,
        categories=["testing"],
        path="skills/python/pytest.md",
        description="Pytest patterns",
    ),
    IndexEntry(
        id="typescript-react",
        name="React Patterns",
        language="typescript",
        framework="React",
        categories=["architecture"],
        path="skills/typescript/react.md",
        description="React patterns",
    ),
]


class TestMatching:
    def test_match_by_language(self) -> None:
        conv = _make_conventions(["python"])
        matched, skipped = _match_entries(_SAMPLE_ENTRIES, conv)
        ids = [e.id for e in matched]
        assert "python-fastapi" not in ids  # framework mismatch (no FastAPI detected)
        assert "python-pytest" in ids       # language match, no framework required
        assert "typescript-react" not in ids  # wrong language

    def test_match_by_framework(self) -> None:
        conv = _make_conventions(["python"], frameworks=["FastAPI"])
        matched, skipped = _match_entries(_SAMPLE_ENTRIES, conv)
        ids = [e.id for e in matched]
        assert "python-fastapi" in ids
        assert "python-pytest" in ids

    def test_skip_covered_categories(self) -> None:
        conv = _make_conventions(
            ["python"],
            covered_categories=[PatternCategory.TESTING],
        )
        matched, skipped = _match_entries(_SAMPLE_ENTRIES, conv)
        # python-pytest only covers "testing" which is already covered → filtered out
        ids = [e.id for e in matched]
        assert "python-pytest" not in ids
        assert "testing" in skipped

    def test_partial_category_overlap_keeps_entry(self) -> None:
        conv = _make_conventions(
            ["python"],
            frameworks=["FastAPI"],
            covered_categories=[PatternCategory.TESTING],
        )
        matched, skipped = _match_entries(_SAMPLE_ENTRIES, conv)
        # python-fastapi covers testing + error-handling; testing covered but error-handling isn't → keep it
        ids = [e.id for e in matched]
        assert "python-fastapi" in ids

    def test_no_matches_returns_empty(self) -> None:
        conv = _make_conventions(["go"])
        matched, skipped = _match_entries(_SAMPLE_ENTRIES, conv)
        assert matched == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_enricher.py::TestMatching -v`
Expected: FAIL — `ImportError: cannot import name '_match_entries'`

- [ ] **Step 3: Implement matching logic**

Add to `skillgen/enricher.py`:

```python
from skillgen.models import (
    EnrichmentResult,
    IndexEntry,
    PatternCategory,
    ProjectConventions,
)


# Map from category slug (used in index) to PatternCategory enum
_CATEGORY_MAP: dict[str, PatternCategory] = {cat.value: cat for cat in PatternCategory}


def _match_entries(
    entries: list[IndexEntry],
    conventions: ProjectConventions,
) -> tuple[list[IndexEntry], list[str]]:
    """Match index entries against project conventions. Returns (matched, skipped_categories)."""
    detected_langs = {li.language.value for li in conventions.project_info.languages}
    detected_frameworks = {fw.name for fw in conventions.project_info.frameworks}
    covered_categories = {
        cat.value for cat, summary in conventions.categories.items() if summary.entries
    }

    matched: list[IndexEntry] = []
    skipped_cats: set[str] = set()

    for entry in entries:
        # Language must match
        if entry.language not in detected_langs:
            continue

        # Framework must match if specified
        if entry.framework is not None and entry.framework not in detected_frameworks:
            continue

        # Check if ALL categories are already covered locally
        entry_cats = set(entry.categories)
        uncovered = entry_cats - covered_categories
        if not uncovered:
            skipped_cats.update(entry_cats)
            continue

        matched.append(entry)

    return matched, sorted(skipped_cats)


def search(
    conventions: ProjectConventions,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> EnrichmentResult:
    """Fetch index and find matching community skills. No files written."""
    errors: list[str] = []
    entries = _fetch_index(cache_dir=cache_dir, no_cache=no_cache)

    if not entries:
        errors.append("Could not fetch skill index")
        return EnrichmentResult(matched=[], skipped_categories=[], errors=errors)

    matched, skipped = _match_entries(entries, conventions)
    return EnrichmentResult(matched=matched, skipped_categories=skipped, errors=errors)
```

Update the imports at the top of `enricher.py` to include the new types.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_enricher.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add skillgen/enricher.py tests/test_enricher.py
git commit -m "feat(enricher): add matching logic with language/framework/category filtering"
```

---

### Task 4: Implement Skill Download and Apply

**Files:**
- Modify: `skillgen/enricher.py`
- Modify: `tests/test_enricher.py`

- [ ] **Step 1: Write failing tests for download and apply**

Append to `tests/test_enricher.py`:

```python
from skillgen.enricher import _fetch_skill_content, apply


class TestFetchSkillContent:
    def test_fetch_skill_from_network(self, tmp_path: Path) -> None:
        content = b"# Pytest Patterns\n\n## Fixtures\n- Use conftest.py\n"
        mock_response = MagicMock()
        mock_response.read.return_value = content
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("skillgen.enricher.urlopen", return_value=mock_response):
            result = _fetch_skill_content("skills/python/pytest.md", cache_dir=tmp_path, no_cache=True)

        assert result is not None
        assert "Pytest Patterns" in result

    def test_fetch_skill_404_returns_none(self, tmp_path: Path) -> None:
        with patch("skillgen.enricher.urlopen", side_effect=OSError("404")):
            result = _fetch_skill_content("skills/nonexistent.md", cache_dir=tmp_path, no_cache=True)

        assert result is None


class TestApply:
    def test_apply_writes_claude_skills(self, tmp_path: Path) -> None:
        entry = IndexEntry(
            id="python-pytest",
            name="Pytest Patterns",
            language="python",
            framework=None,
            categories=["testing"],
            path="skills/python/pytest.md",
            description="Pytest patterns",
        )
        content = "# Pytest Patterns\n\n## Fixtures\n- Use conftest.py\n"

        with patch("skillgen.enricher._fetch_skill_content", return_value=content):
            written = apply(
                entries=[entry],
                target_dir=tmp_path,
                output_format=OutputFormat.CLAUDE,
                cache_dir=tmp_path / "cache",
            )

        assert len(written) == 1
        assert written[0].format == "claude"
        file_path = tmp_path / ".claude" / "skills" / "community" / "pytest-patterns.md"
        assert file_path.exists()
        file_content = file_path.read_text()
        assert "Community skill" in file_content
        assert "Pytest Patterns" in file_content

    def test_apply_writes_both_formats(self, tmp_path: Path) -> None:
        entry = IndexEntry(
            id="python-pytest",
            name="Pytest Patterns",
            language="python",
            framework=None,
            categories=["testing"],
            path="skills/python/pytest.md",
            description="Pytest patterns",
        )
        content = "# Pytest Patterns\n\n## Fixtures\n- Use conftest.py\n"

        with patch("skillgen.enricher._fetch_skill_content", return_value=content):
            written = apply(
                entries=[entry],
                target_dir=tmp_path,
                output_format=OutputFormat.ALL,
                cache_dir=tmp_path / "cache",
            )

        assert len(written) == 2  # claude + cursor
        formats = {w.format for w in written}
        assert "claude" in formats
        assert "cursor" in formats

    def test_apply_with_pick_filters(self, tmp_path: Path) -> None:
        entries = [
            IndexEntry(id="a", name="A", language="python", framework=None,
                       categories=["testing"], path="a.md", description="A"),
            IndexEntry(id="b", name="B", language="python", framework=None,
                       categories=["style"], path="b.md", description="B"),
        ]
        content = "# Skill\n\nContent here.\n"

        with patch("skillgen.enricher._fetch_skill_content", return_value=content):
            written = apply(
                entries=entries,
                target_dir=tmp_path,
                output_format=OutputFormat.CLAUDE,
                pick=[1],  # Only first entry
                cache_dir=tmp_path / "cache",
            )

        assert len(written) == 1

    def test_apply_skips_failed_downloads(self, tmp_path: Path) -> None:
        entry = IndexEntry(
            id="python-pytest",
            name="Pytest",
            language="python",
            framework=None,
            categories=["testing"],
            path="skills/python/pytest.md",
            description="Pytest",
        )

        with patch("skillgen.enricher._fetch_skill_content", return_value=None):
            written = apply(
                entries=[entry],
                target_dir=tmp_path,
                output_format=OutputFormat.CLAUDE,
                cache_dir=tmp_path / "cache",
            )

        assert written == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_enricher.py::TestFetchSkillContent tests/test_enricher.py::TestApply -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement download and apply**

Add to `skillgen/enricher.py`:

```python
from datetime import date

from skillgen.models import (
    EnrichmentResult,
    IndexEntry,
    OutputFormat,
    PatternCategory,
    ProjectConventions,
    WrittenFile,
)


def _fetch_skill_content(
    path: str,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> str | None:
    """Fetch a single skill file's content. Returns None on failure."""
    cache = _get_cache_dir(cache_dir)
    cache_filename = f"skills/{path.replace('/', '_')}"

    if not no_cache:
        cached = _read_cache(cache, cache_filename, CACHE_TTL_SECONDS)
        if cached is not None:
            return cached

    url = BASE_URL + path
    raw = _fetch_url(url)
    if raw is None:
        # Try stale cache
        stale = _read_cache(cache, cache_filename, max_age_seconds=999_999_999)
        return stale

    content = raw.decode("utf-8", errors="replace")
    _write_cache(cache, cache_filename, content)
    return content


def _slugify(name: str) -> str:
    """Convert a skill name to a filename-safe slug."""
    return name.lower().replace(" ", "-").replace("_", "-")


def _format_community_claude(entry: IndexEntry, content: str) -> str:
    """Format a community skill for .claude/skills/community/*.md."""
    today = date.today().isoformat()
    return (
        f"<!-- Source: skillgen/skill-index | Community skill, not derived from your code -->\n"
        f"<!-- Skill: {entry.id} | Last fetched: {today} -->\n"
        f"\n"
        f"---\n"
        f"name: {_slugify(entry.name)}\n"
        f"description: {entry.description}\n"
        f"---\n"
        f"\n"
        f"{content}\n"
    )


def _format_community_cursor(entry: IndexEntry, content: str) -> str:
    """Format a community skill for .cursor/rules/community/*.mdc."""
    today = date.today().isoformat()
    return (
        f"<!-- Source: skillgen/skill-index | Community skill, not derived from your code -->\n"
        f"<!-- Skill: {entry.id} | Last fetched: {today} -->\n"
        f"\n"
        f"---\n"
        f"description: {entry.description}\n"
        f"globs: *\n"
        f"alwaysApply: false\n"
        f"---\n"
        f"\n"
        f"{content}\n"
    )


def apply(
    entries: list[IndexEntry],
    target_dir: Path,
    output_format: OutputFormat,
    pick: list[int] | None = None,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> list[WrittenFile]:
    """Download selected community skills and write to disk."""
    # Filter by pick (1-indexed)
    if pick is not None:
        entries = [entries[i - 1] for i in pick if 1 <= i <= len(entries)]

    written: list[WrittenFile] = []

    for entry in entries:
        content = _fetch_skill_content(entry.path, cache_dir=cache_dir, no_cache=no_cache)
        if content is None:
            logger.warning("Could not download skill '%s', skipping", entry.id)
            continue

        slug = _slugify(entry.name)

        if output_format in (OutputFormat.CLAUDE, OutputFormat.ALL):
            claude_dir = target_dir / ".claude" / "skills" / "community"
            claude_dir.mkdir(parents=True, exist_ok=True)
            claude_path = claude_dir / f"{slug}.md"
            claude_content = _format_community_claude(entry, content)
            claude_path.write_text(claude_content, encoding="utf-8")
            written.append(WrittenFile(
                path=claude_path, format="claude",
                line_count=claude_content.count("\n") + 1,
            ))

        if output_format in (OutputFormat.CURSOR, OutputFormat.ALL):
            cursor_dir = target_dir / ".cursor" / "rules" / "community"
            cursor_dir.mkdir(parents=True, exist_ok=True)
            cursor_path = cursor_dir / f"{slug}.mdc"
            cursor_content = _format_community_cursor(entry, content)
            cursor_path.write_text(cursor_content, encoding="utf-8")
            written.append(WrittenFile(
                path=cursor_path, format="cursor",
                line_count=cursor_content.count("\n") + 1,
            ))

    return written
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_enricher.py -v`
Expected: All 18 tests PASS

- [ ] **Step 5: Lint and type check**

Run: `ruff check skillgen/enricher.py tests/test_enricher.py && mypy skillgen/enricher.py --ignore-missing-imports`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add skillgen/enricher.py tests/test_enricher.py
git commit -m "feat(enricher): add skill download, formatting, and apply with --pick support"
```

---

### Task 5: Add Renderer Functions for Enrich Output

**Files:**
- Modify: `skillgen/renderer.py`

- [ ] **Step 1: Add render_enrich_preview and render_enrich_applied**

Add to `skillgen/renderer.py`:

```python
from skillgen.models import EnrichmentResult, IndexEntry, WrittenFile


def render_enrich_preview(result: EnrichmentResult) -> None:
    """Render the --enrich preview table showing matched community skills."""
    if not result.matched:
        if result.errors:
            console.print(f"\n[yellow]Warning:[/yellow] {result.errors[0]}")
        else:
            console.print(
                "\n[dim]No community skills found matching this project.[/dim]"
            )
        return

    console.print(
        f"\n[bold]Found {len(result.matched)} community skill(s):[/bold]"
    )

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Skill", style="cyan", min_width=24)
    table.add_column("Categories", style="green")
    table.add_column("Description", style="dim", max_width=40)

    for i, entry in enumerate(result.matched, 1):
        table.add_row(
            str(i),
            entry.name,
            ", ".join(entry.categories),
            entry.description,
        )

    console.print(table)

    if result.skipped_categories:
        console.print(
            f"\n[dim]Skipped (already covered locally): "
            f"{', '.join(result.skipped_categories)}[/dim]"
        )

    console.print(
        "\n[bold]To install:[/bold] skillgen . --enrich --apply"
        "\n[bold]To pick:[/bold]    skillgen . --enrich --apply --pick 1,2"
    )


def render_enrich_applied(written: list[WrittenFile]) -> None:
    """Render the result of --enrich --apply."""
    if not written:
        console.print("\n[dim]No community skill files written.[/dim]")
        return

    table = Table(
        title="Community Skill Files Installed",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("File", style="cyan", min_width=40)
    table.add_column("Format", style="green", justify="center")
    table.add_column("Lines", style="yellow", justify="right")

    for wf in sorted(written, key=lambda f: str(f.path)):
        table.add_row(str(wf.path), wf.format.title(), str(wf.line_count))

    console.print()
    console.print(table)
    console.print(
        f"\n[bold green]Done![/bold green] "
        f"{len(written)} community skill file(s) installed."
    )
```

- [ ] **Step 2: Lint check**

Run: `ruff check skillgen/renderer.py`
Expected: All checks passed

- [ ] **Step 3: Commit**

```bash
git add skillgen/renderer.py
git commit -m "feat(renderer): add enrich preview and applied output renderers"
```

---

### Task 6: Wire Up CLI Flags

**Files:**
- Modify: `skillgen/cli.py`

- [ ] **Step 1: Add --enrich, --apply, --pick, --no-cache flags**

Add these options to the `main()` function parameters, after `--no-tree-sitter`:

```python
    enrich: bool = typer.Option(
        False,
        "--enrich",
        help="Search online index for community skills matching this project.",
    ),
    apply_enrich: bool = typer.Option(
        False,
        "--apply",
        help="Download and install matched community skills (use with --enrich).",
    ),
    pick: str | None = typer.Option(
        None,
        "--pick",
        help="Comma-separated skill numbers to cherry-pick (e.g., --pick 1,3).",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Force re-fetch of online skill index, ignoring cache.",
    ),
```

- [ ] **Step 2: Add flag validation after path validation**

After the path validation block (line ~158), add:

```python
    # --- Flag validation ---
    if apply_enrich and not enrich:
        _console.print("[red]Error:[/red] Use --enrich --apply together.")
        raise typer.Exit(code=1)
    if pick is not None and not apply_enrich:
        _console.print("[red]Error:[/red] Use --pick with --enrich --apply.")
        raise typer.Exit(code=1)

    pick_indices: list[int] | None = None
    if pick is not None:
        try:
            pick_indices = [int(x.strip()) for x in pick.split(",")]
        except ValueError:
            _console.print("[red]Error:[/red] --pick must be comma-separated numbers (e.g., --pick 1,3).")
            raise typer.Exit(code=1)
```

- [ ] **Step 3: Add enrichment step after synthesis**

After the synthesis step and JSON output block, before `# Phase 3: Generate`, add:

```python
            # Phase 2.75: Enrich (optional, network)
            if enrich:
                from skillgen.enricher import apply as enrich_apply
                from skillgen.enricher import search as enrich_search
                from skillgen.renderer import render_enrich_applied, render_enrich_preview

                task_enrich = progress.add_task("Searching community skills...", total=1)
                enrich_result = enrich_search(
                    conventions, cache_dir=None, no_cache=no_cache
                )
                progress.update(task_enrich, completed=1)

                if apply_enrich:
                    # Validate --pick range
                    if pick_indices:
                        max_idx = len(enrich_result.matched)
                        invalid = [i for i in pick_indices if i < 1 or i > max_idx]
                        if invalid:
                            progress.stop()
                            _console.print(
                                f"[red]Error:[/red] Invalid --pick values: {invalid}. "
                                f"Only {max_idx} skills matched (valid range: 1-{max_idx})."
                            )
                            raise typer.Exit(code=1)

                    task_apply = progress.add_task("Installing community skills...", total=1)
                    enrich_written = enrich_apply(
                        entries=enrich_result.matched,
                        target_dir=resolved,
                        output_format=format,
                        pick=pick_indices,
                        no_cache=no_cache,
                    )
                    progress.update(task_apply, completed=1)
```

- [ ] **Step 4: Add rendering after the progress block**

After `render_summary` in the rendering section, add:

```python
        # Render enrichment results
        if enrich:
            if apply_enrich:
                render_enrich_applied(enrich_written)
            else:
                render_enrich_preview(enrich_result)
```

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All existing tests PASS (no tests broken by new flags — they have defaults)

- [ ] **Step 6: Run lint and type check**

Run: `ruff check skillgen/cli.py && mypy skillgen/ --ignore-missing-imports`
Expected: All checks passed

- [ ] **Step 7: Commit**

```bash
git add skillgen/cli.py
git commit -m "feat(cli): wire up --enrich, --apply, --pick, --no-cache flags"
```

---

### Task 7: End-to-End Integration Test

**Files:**
- Modify: `tests/test_enricher.py`

- [ ] **Step 1: Write E2E test**

Append to `tests/test_enricher.py`:

```python
from skillgen.enricher import search, apply


class TestEndToEnd:
    def test_search_and_apply_pipeline(self, tmp_path: Path) -> None:
        """Full pipeline: search → preview → apply with mocked network."""
        index_data = json.dumps({
            "version": 1,
            "skills": [
                {
                    "id": "python-pytest",
                    "name": "Pytest Patterns",
                    "language": "python",
                    "framework": None,
                    "categories": ["testing"],
                    "path": "skills/python/pytest.md",
                    "description": "Pytest best practices",
                },
                {
                    "id": "typescript-react",
                    "name": "React Patterns",
                    "language": "typescript",
                    "framework": "React",
                    "categories": ["architecture"],
                    "path": "skills/typescript/react.md",
                    "description": "React patterns",
                },
            ],
        })
        skill_content = "# Pytest Patterns\n\n## Fixtures\n- Use conftest.py for shared fixtures\n"

        conv = _make_conventions(["python"])  # No frameworks, no covered categories

        # Mock both the index fetch and skill download
        def mock_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            mock_resp = MagicMock()
            if "index.json" in url:
                mock_resp.read.return_value = index_data.encode()
            else:
                mock_resp.read.return_value = skill_content.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        cache = tmp_path / "cache"

        with patch("skillgen.enricher.urlopen", side_effect=mock_urlopen):
            # Step 1: Search
            result = search(conv, cache_dir=cache, no_cache=True)

            assert len(result.matched) == 1  # Only python-pytest (TS filtered out)
            assert result.matched[0].id == "python-pytest"

            # Step 2: Apply
            written = apply(
                entries=result.matched,
                target_dir=tmp_path,
                output_format=OutputFormat.ALL,
                cache_dir=cache,
                no_cache=True,
            )

        # Verify files
        assert len(written) == 2  # claude + cursor
        claude_file = tmp_path / ".claude" / "skills" / "community" / "pytest-patterns.md"
        cursor_file = tmp_path / ".cursor" / "rules" / "community" / "pytest-patterns.mdc"
        assert claude_file.exists()
        assert cursor_file.exists()
        assert "conftest.py" in claude_file.read_text()
        assert "Community skill" in cursor_file.read_text()

    def test_search_with_no_network_no_cache(self, tmp_path: Path) -> None:
        """Network failure with empty cache returns empty result with error."""
        conv = _make_conventions(["python"])

        with patch("skillgen.enricher.urlopen", side_effect=OSError("offline")):
            result = search(conv, cache_dir=tmp_path / "empty_cache", no_cache=True)

        assert result.matched == []
        assert len(result.errors) > 0
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS (114 existing + ~20 new enricher tests)

- [ ] **Step 3: Lint and type check everything**

Run: `ruff check skillgen/ tests/ && mypy skillgen/ --ignore-missing-imports`
Expected: All checks passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_enricher.py
git commit -m "test(enricher): add end-to-end integration test with mocked network"
```

---

### Task 8: Manual Smoke Test

- [ ] **Step 1: Verify --enrich without network shows graceful failure**

Run: `skillgen . --enrich --verbose`
Expected: Local generation completes normally. Enrichment shows a warning or "no skills found" (since the index repo doesn't exist yet). No crash.

- [ ] **Step 2: Verify --apply without --enrich shows error**

Run: `skillgen . --apply`
Expected: Error message: "Use --enrich --apply together."

- [ ] **Step 3: Verify --pick without --apply shows error**

Run: `skillgen . --enrich --pick 1`
Expected: Error message: "Use --pick with --enrich --apply."

- [ ] **Step 4: Verify --help shows new flags**

Run: `skillgen --help`
Expected: `--enrich`, `--apply`, `--pick`, `--no-cache` all visible in help output.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: online skill enrichment with --enrich and --apply flags

Add community skill discovery from GitHub-hosted index.
- --enrich: preview available community skills
- --enrich --apply: download and install selected skills
- --pick: cherry-pick specific skills by number
- --no-cache: force re-fetch ignoring 24h cache
- community/ subdirectory keeps online skills separate from local
- All network calls are non-fatal with graceful fallback"
```

---

## Self-Review Checklist

**Spec coverage:**
- Index fetching + caching: Task 2
- Matching logic (language/framework/category): Task 3
- Skill download + apply + pick: Task 4
- Terminal output (preview + applied): Task 5
- CLI flags (--enrich, --apply, --pick, --no-cache): Task 6
- Flag validation: Task 6 Step 2
- Error handling (network failure, malformed JSON, 404): Tasks 2-4 tests
- Community subdirectory output: Task 4
- File tagging (Source comment): Task 4
- E2E test: Task 7

**Placeholder scan:** No TBD, TODO, or "fill in later" found.

**Type consistency:** `IndexEntry`, `EnrichmentResult`, `WrittenFile` used consistently. `_fetch_index` returns `list[IndexEntry]`. `search` returns `EnrichmentResult`. `apply` returns `list[WrittenFile]`. All match the spec.
