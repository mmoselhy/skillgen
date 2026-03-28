"""Tests for the enricher module."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from skillgen.enricher import (
    _fetch_index,
    _fetch_skill_content,
    _get_cache_dir,
    _match_entries,
    _read_cache,
    _slugify,
    _write_cache,
    apply,
    search,
)
from skillgen.models import (
    CategorySummary,
    EnrichmentResult,
    FrameworkInfo,
    IndexEntry,
    Language,
    LanguageInfo,
    OutputFormat,
    PatternCategory,
    ProjectConventions,
    ProjectInfo,
)

# --- Helpers ---


def _make_conventions(
    languages: list[Language] | None = None,
    frameworks: list[str] | None = None,
    categories: list[PatternCategory] | None = None,
) -> ProjectConventions:
    """Build a minimal ProjectConventions for tests."""
    if languages is None:
        languages = [Language.PYTHON]

    lang_infos = [
        LanguageInfo(language=lang, file_count=10, file_paths=[], percentage=100.0)
        for lang in languages
    ]

    fw_infos = [
        FrameworkInfo(name=fw, language=languages[0], evidence="detected")
        for fw in (frameworks or [])
    ]

    project_info = ProjectInfo(
        root_path=Path("/test/project"),
        languages=lang_infos,
        frameworks=fw_infos,
        total_files=100,
        source_files=50,
    )

    cat_dict: dict[PatternCategory, CategorySummary] = {}
    for cat in categories or []:
        cat_dict[cat] = CategorySummary(
            category=cat,
            entries=[],
            files_analyzed=10,
            raw_pattern_count=5,
        )

    return ProjectConventions(
        project_info=project_info,
        categories=cat_dict,
        config_settings={},
        config_files_parsed=[],
        files_analyzed=50,
        analysis_duration_seconds=1.0,
    )


def _make_index_entry(
    id: str = "pytest-patterns",
    name: str = "Pytest Patterns",
    language: str = "python",
    framework: str | None = "pytest",
    categories: list[str] | None = None,
    path: str = "skills/python/pytest-patterns.md",
    description: str = "Common pytest patterns and best practices",
    source_repo: str = "",
    content_url: str = "",
    trust: str = "contributed",
    format: str = "markdown",
    tags: list[str] | None = None,
    updated_at: str = "",
) -> IndexEntry:
    """Build a test IndexEntry."""
    return IndexEntry(
        id=id,
        name=name,
        language=language,
        framework=framework,
        categories=categories or ["testing"],
        path=path,
        description=description,
        source_repo=source_repo,
        content_url=content_url,
        trust=trust,
        format=format,
        tags=tags or [],
        updated_at=updated_at,
    )


def _make_index_json(entries: list[IndexEntry] | None = None) -> str:
    """Serialize entries to JSON matching the index format."""
    if entries is None:
        entries = [_make_index_entry()]
    data = []
    for e in entries:
        item: dict[str, object] = {
            "id": e.id,
            "name": e.name,
            "language": e.language,
            "categories": e.categories,
            "path": e.path,
            "description": e.description,
        }
        if e.framework is not None:
            item["framework"] = e.framework
        data.append(item)
    return json.dumps(data)


def _mock_urlopen_response(data: str) -> MagicMock:
    """Create a MagicMock that behaves like a urlopen response context manager."""
    mock_response = MagicMock()
    mock_response.read.return_value = data.encode("utf-8")
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


# --- Test classes ---


class TestCaching:
    """Test cache read/write operations."""

    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        """Write content to cache, then read it back."""
        _write_cache(tmp_path, "test.json", '{"hello": "world"}')
        result = _read_cache(tmp_path, "test.json", max_age_seconds=3600)
        assert result == '{"hello": "world"}'

    def test_expired_cache_returns_none(self, tmp_path: Path) -> None:
        """Expired cache file returns None."""
        _write_cache(tmp_path, "old.json", "old data")
        # Set mtime to the past.
        cache_file = tmp_path / "old.json"
        old_time = time.time() - 7200  # 2 hours ago
        import os

        os.utime(cache_file, (old_time, old_time))
        result = _read_cache(tmp_path, "old.json", max_age_seconds=3600)
        assert result is None

    def test_missing_cache_returns_none(self, tmp_path: Path) -> None:
        """Missing cache file returns None."""
        result = _read_cache(tmp_path, "nonexistent.json", max_age_seconds=3600)
        assert result is None

    def test_default_cache_dir(self) -> None:
        """Default cache dir is ~/.cache/skillgen/."""
        result = _get_cache_dir(None)
        assert result == Path.home() / ".cache" / "skillgen"


class TestFetchIndex:
    """Test index fetching with mocked network."""

    @patch("skillgen.enricher.urlopen")
    def test_fetch_from_network(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Fetch index from network when cache is empty."""
        entry = _make_index_entry()
        index_json = _make_index_json([entry])
        mock_urlopen.return_value = _mock_urlopen_response(index_json)

        entries = _fetch_index(cache_dir=tmp_path, no_cache=True)
        assert len(entries) == 1
        assert entries[0].id == "pytest-patterns"
        mock_urlopen.assert_called_once()

    @patch("skillgen.enricher.urlopen")
    def test_use_fresh_cache(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Use cached index when it is fresh."""
        entry = _make_index_entry()
        index_json = _make_index_json([entry])
        _write_cache(tmp_path, "index.json", index_json)

        entries = _fetch_index(cache_dir=tmp_path, no_cache=False)
        assert len(entries) == 1
        assert entries[0].id == "pytest-patterns"
        # Should NOT have called network.
        mock_urlopen.assert_not_called()

    @patch("skillgen.enricher.urlopen")
    def test_network_failure_returns_empty(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """Network failure with no cache returns empty list."""
        mock_urlopen.side_effect = OSError("Connection refused")

        entries = _fetch_index(cache_dir=tmp_path, no_cache=True)
        assert entries == []

    @patch("skillgen.enricher.urlopen")
    def test_malformed_json_returns_empty(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """Malformed JSON returns empty list."""
        mock_urlopen.return_value = _mock_urlopen_response("{not valid json")

        entries = _fetch_index(cache_dir=tmp_path, no_cache=True)
        assert entries == []


class TestMatching:
    """Test entry matching against project conventions."""

    def test_match_by_language(self) -> None:
        """Entries matching the project language are returned."""
        conventions = _make_conventions(languages=[Language.PYTHON])
        python_entry = _make_index_entry(language="python", framework=None)
        go_entry = _make_index_entry(id="go-patterns", language="go", framework=None)

        matched, _skipped = _match_entries([python_entry, go_entry], conventions)
        assert len(matched) == 1
        assert matched[0].id == "pytest-patterns"

    def test_match_by_framework(self) -> None:
        """Entries matching both language and framework are returned."""
        conventions = _make_conventions(
            languages=[Language.PYTHON], frameworks=["pytest"]
        )
        pytest_entry = _make_index_entry(framework="pytest")
        django_entry = _make_index_entry(
            id="django-patterns", framework="django", path="skills/python/django.md"
        )

        matched, _skipped = _match_entries([pytest_entry, django_entry], conventions)
        assert len(matched) == 1
        assert matched[0].id == "pytest-patterns"

    def test_skip_covered_categories(self) -> None:
        """Entries whose categories are all locally covered are skipped."""
        conventions = _make_conventions(
            languages=[Language.PYTHON],
            categories=[PatternCategory.TESTING],
        )
        entry = _make_index_entry(
            framework=None, categories=["testing"]
        )

        matched, skipped = _match_entries([entry], conventions)
        assert len(matched) == 0
        assert "Pytest Patterns" in skipped

    def test_partial_overlap_keeps_entry(self) -> None:
        """Entries with partial category overlap (not all covered) are kept."""
        conventions = _make_conventions(
            languages=[Language.PYTHON],
            categories=[PatternCategory.TESTING],
        )
        entry = _make_index_entry(
            framework=None,
            categories=["testing", "error-handling"],
        )

        matched, skipped = _match_entries([entry], conventions)
        assert len(matched) == 1
        assert len(skipped) == 0

    def test_no_matches_returns_empty(self) -> None:
        """No matching entries returns empty list."""
        conventions = _make_conventions(languages=[Language.GO])
        entry = _make_index_entry(language="python")

        matched, skipped = _match_entries([entry], conventions)
        assert len(matched) == 0
        assert len(skipped) == 0


class TestFetchSkillContent:
    """Test individual skill content fetching."""

    @patch("skillgen.enricher.urlopen")
    def test_fetch_from_network(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Fetch skill content from network."""
        skill_md = "# Pytest Patterns\n\nUse fixtures wisely."
        mock_urlopen.return_value = _mock_urlopen_response(skill_md)

        result = _fetch_skill_content(
            "skills/python/pytest-patterns.md", cache_dir=tmp_path, no_cache=True
        )
        assert result == skill_md

    @patch("skillgen.enricher.urlopen")
    def test_404_returns_none(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """HTTP error returns None."""
        mock_urlopen.side_effect = OSError("HTTP 404")

        result = _fetch_skill_content(
            "skills/python/nonexistent.md", cache_dir=tmp_path, no_cache=True
        )
        assert result is None


class TestApply:
    """Test downloading and writing community skills."""

    @patch("skillgen.enricher.urlopen")
    def test_writes_claude_format(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Apply writes .claude/skills/community/*.md files."""
        skill_md = "# Pytest Patterns\n\nBest practices."
        mock_urlopen.return_value = _mock_urlopen_response(skill_md)

        entry = _make_index_entry()
        written = apply(
            [entry],
            target_dir=tmp_path,
            output_format=OutputFormat.CLAUDE,
            cache_dir=tmp_path / "cache",
            no_cache=True,
        )

        assert len(written) == 1
        assert written[0].format == "claude"
        assert written[0].path.exists()
        content = written[0].path.read_text(encoding="utf-8")
        assert "Community skill: Pytest Patterns" in content
        assert "Best practices." in content

    @patch("skillgen.enricher.urlopen")
    def test_writes_both_formats(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Apply writes both claude and cursor files when format is ALL."""
        skill_md = "# Pytest Patterns\n\nContent here."
        mock_urlopen.return_value = _mock_urlopen_response(skill_md)

        entry = _make_index_entry()
        written = apply(
            [entry],
            target_dir=tmp_path,
            output_format=OutputFormat.ALL,
            cache_dir=tmp_path / "cache",
            no_cache=True,
        )

        assert len(written) == 2
        formats = {w.format for w in written}
        assert formats == {"claude", "cursor"}

        # Check cursor file has frontmatter.
        cursor_file = next(w for w in written if w.format == "cursor")
        cursor_content = cursor_file.path.read_text(encoding="utf-8")
        assert "alwaysApply: false" in cursor_content

    @patch("skillgen.enricher.urlopen")
    def test_pick_filters_entries(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Pick list filters to only selected entries."""
        skill_md = "# Content"
        mock_urlopen.return_value = _mock_urlopen_response(skill_md)

        entry1 = _make_index_entry(id="entry-1", name="Entry One")
        entry2 = _make_index_entry(id="entry-2", name="Entry Two")

        written = apply(
            [entry1, entry2],
            target_dir=tmp_path,
            output_format=OutputFormat.CLAUDE,
            pick=["entry-1"],
            cache_dir=tmp_path / "cache",
            no_cache=True,
        )

        assert len(written) == 1
        assert "entry-one" in str(written[0].path)

    @patch("skillgen.enricher.urlopen")
    def test_skips_failed_downloads(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """Failed downloads are skipped, not raising."""
        mock_urlopen.side_effect = OSError("Network error")

        entry = _make_index_entry()
        written = apply(
            [entry],
            target_dir=tmp_path,
            output_format=OutputFormat.CLAUDE,
            cache_dir=tmp_path / "cache",
            no_cache=True,
        )

        assert len(written) == 0


class TestEndToEnd:
    """End-to-end tests with mocked network."""

    @patch("skillgen.enricher.urlopen")
    def test_search_then_apply(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        """Full pipeline: search the index, then apply matched skills."""
        entry = _make_index_entry(framework=None)
        index_json = _make_index_json([entry])
        skill_md = "# Pytest Patterns\n\nUse fixtures."

        # First call: index fetch; second call: skill content fetch.
        mock_urlopen.side_effect = [
            _mock_urlopen_response(index_json),
            _mock_urlopen_response(skill_md),
        ]

        conventions = _make_conventions(languages=[Language.PYTHON])
        result = search(conventions, cache_dir=tmp_path, no_cache=True)

        assert len(result.matched) == 1
        assert len(result.errors) == 0

        written = apply(
            result.matched,
            target_dir=tmp_path,
            output_format=OutputFormat.CLAUDE,
            cache_dir=tmp_path / "cache",
            no_cache=True,
        )

        assert len(written) == 1
        content = written[0].path.read_text(encoding="utf-8")
        assert "Use fixtures." in content

    @patch("skillgen.enricher.urlopen")
    def test_no_network_no_cache_returns_empty_with_error(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """No network and no cache returns empty result with error message."""
        mock_urlopen.side_effect = OSError("No network")

        conventions = _make_conventions(languages=[Language.PYTHON])
        result = search(conventions, cache_dir=tmp_path, no_cache=True)

        assert isinstance(result, EnrichmentResult)
        assert len(result.matched) == 0
        assert len(result.errors) > 0
        assert "Could not fetch" in result.errors[0]


class TestSlugify:
    """Test the slugify helper."""

    def test_basic_slugify(self) -> None:
        assert _slugify("Pytest Patterns") == "pytest-patterns"

    def test_special_characters(self) -> None:
        assert _slugify("React/Next.js Patterns!") == "react-next-js-patterns"

    def test_leading_trailing_stripped(self) -> None:
        assert _slugify("  --hello--  ") == "hello"


class TestParseIndexV2:
    """Test parsing v2 index format with new fields."""

    def test_parse_v2_with_all_fields(self) -> None:
        from skillgen.enricher import _parse_index

        content = json.dumps({
            "version": 2,
            "updated": "2026-03-28T04:30:00Z",
            "sources_crawled": ["anthropics/skills"],
            "skills": [{
                "id": "anthropic-frontend",
                "name": "Frontend Design",
                "language": "any",
                "framework": None,
                "categories": ["architecture"],
                "path": "skills/frontend/SKILL.md",
                "description": "Frontend design skill",
                "source_repo": "anthropics/skills",
                "content_url": "https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend/SKILL.md",
                "trust": "official",
                "format": "skill-md",
                "tags": ["frontend"],
                "updated_at": "2026-03-15",
            }],
        })
        entries = _parse_index(content)
        assert len(entries) == 1
        assert entries[0].trust == "official"
        assert entries[0].source_repo == "anthropics/skills"
        assert entries[0].content_url.startswith("https://")

    def test_parse_v1_gets_defaults(self) -> None:
        from skillgen.enricher import _parse_index

        content = json.dumps({"skills": [{
            "id": "old-skill",
            "name": "Old Skill",
            "language": "python",
            "categories": ["testing"],
            "path": "old.md",
            "description": "Legacy",
        }]})
        entries = _parse_index(content)
        assert len(entries) == 1
        assert entries[0].trust == "contributed"
        assert entries[0].source_repo == ""
        assert entries[0].content_url == ""


class TestTrustFiltering:
    """Test trust-based filtering in _match_entries."""

    def test_filter_official_only(self) -> None:
        entries = [
            _make_index_entry(id="a", trust="official", framework=None, language="python"),
            _make_index_entry(id="b", trust="community", framework=None, language="python"),
            _make_index_entry(id="c", trust="contributed", framework=None, language="python"),
        ]
        conventions = _make_conventions(categories=[])
        matched, _ = _match_entries(entries, conventions, trust_filter={"official"})
        assert len(matched) == 1
        assert matched[0].id == "a"

    def test_filter_multiple_tiers(self) -> None:
        entries = [
            _make_index_entry(id="a", trust="official", framework=None, language="python"),
            _make_index_entry(id="b", trust="community", framework=None, language="python"),
            _make_index_entry(id="c", trust="contributed", framework=None, language="python"),
        ]
        conventions = _make_conventions(categories=[])
        matched, _ = _match_entries(entries, conventions, trust_filter={"official", "community"})
        assert len(matched) == 2

    def test_no_filter_returns_all(self) -> None:
        entries = [
            _make_index_entry(id="a", trust="official", framework=None, language="python"),
            _make_index_entry(id="b", trust="community", framework=None, language="python"),
        ]
        conventions = _make_conventions(categories=[])
        matched, _ = _match_entries(entries, conventions, trust_filter=None)
        assert len(matched) == 2


class TestIndexEntryV2:
    """Test v2 IndexEntry fields."""

    def test_v2_fields_have_defaults(self) -> None:
        """v2 fields are optional with sensible defaults."""
        entry = IndexEntry(
            id="test", name="Test", language="python", framework=None,
            categories=["testing"], path="test.md", description="Test",
        )
        assert entry.source_repo == ""
        assert entry.content_url == ""
        assert entry.trust == "contributed"
        assert entry.format == "markdown"
        assert entry.tags == []
        assert entry.updated_at == ""

    def test_v2_fields_set_explicitly(self) -> None:
        entry = _make_index_entry(
            source_repo="anthropics/skills",
            content_url="https://raw.githubusercontent.com/anthropics/skills/main/test.md",
            trust="official",
            format="skill-md",
            tags=["frontend"],
            updated_at="2026-03-15",
        )
        assert entry.trust == "official"
        assert entry.source_repo == "anthropics/skills"
        assert entry.tags == ["frontend"]


class TestV2ContentFetching:
    """Test content fetching with content_url."""

    @patch("skillgen.enricher.urlopen")
    def test_uses_content_url_when_available(self, mock_urlopen, tmp_path) -> None:
        from skillgen.enricher import _fetch_skill_content

        mock_response = _mock_urlopen_response("# Skill content")
        mock_urlopen.return_value = mock_response

        entry = _make_index_entry(
            content_url="https://raw.githubusercontent.com/anthropics/skills/main/test.md"
        )
        result = _fetch_skill_content(
            entry.path,
            content_url=entry.content_url,
            cache_dir=tmp_path,
        )
        assert result == "# Skill content"
        call_args = mock_urlopen.call_args
        url_used = call_args[0][0].full_url
        assert "anthropics/skills" in url_used

    @patch("skillgen.enricher.urlopen")
    def test_falls_back_to_base_url(self, mock_urlopen, tmp_path) -> None:
        from skillgen.enricher import _fetch_skill_content

        mock_response = _mock_urlopen_response("# Fallback content")
        mock_urlopen.return_value = mock_response

        result = _fetch_skill_content(
            "skills/python/test.md",
            content_url="",
            cache_dir=tmp_path,
        )
        assert result == "# Fallback content"


class TestV2Formatting:
    """Test updated community skill file formatting."""

    def test_claude_format_includes_trust(self) -> None:
        from skillgen.enricher import _format_community_claude

        entry = _make_index_entry(
            source_repo="anthropics/skills",
            trust="official",
        )
        result = _format_community_claude(entry, "# Content")
        assert "Trust: official" in result
        assert "anthropics/skills" in result

    def test_cursor_format_includes_trust(self) -> None:
        from skillgen.enricher import _format_community_cursor

        entry = _make_index_entry(
            source_repo="PatrickJS/awesome-cursorrules",
            trust="community",
        )
        result = _format_community_cursor(entry, "# Content")
        assert "Trust: community" in result
        assert "PatrickJS/awesome-cursorrules" in result
