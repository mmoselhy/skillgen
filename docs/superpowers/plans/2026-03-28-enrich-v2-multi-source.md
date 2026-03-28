# Enrich v2: Multi-Source Community Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-written skill-index with an automated build pipeline that crawls trusted open-source repos (Anthropic skills, awesome-cursorrules, GitHub copilot instructions, etc.) and produces a rich v2 index with trust tiers. Update the skillgen CLI to display trust/source metadata and support `--trust` filtering.

**Architecture:** A build pipeline in the `mmoselhy/skill-index` repo runs adapters per source, merges results into `index.json`. The skillgen CLI fetches this index at runtime (same flow as v1). Three phases: (1) build pipeline in skill-index, (2) client v2 support in skillgen, (3) skill file updates.

**Tech Stack:** Python 3.11+, GitHub Actions, GitHub REST API (via `urllib.request`), PyYAML (for SKILL.md frontmatter parsing), pytest, Rich (for table rendering), Typer (CLI).

---

## Phase 1: Build Pipeline (skill-index repo)

All Phase 1 tasks are in the `skill-index/` directory at `/home/mmoselhy/projects/skillgen/skill-index/`.

**Note:** The spec defines 6 adapters. This plan implements 3 (anthropic_skills, copilot_instructions, cursorrules) — covering all trust tiers and the highest-value sources. The remaining 3 (anthropic_plugins, claude_md_index, subagents) follow the same pattern and can be added as follow-up tasks using Task 3-5 as templates.

---

### Task 1: Adapter Base Protocol and Data Structures

**Files:**
- Create: `skill-index/adapters/__init__.py`
- Create: `skill-index/adapters/base.py`
- Create: `skill-index/tests/__init__.py`
- Create: `skill-index/tests/test_base.py`

- [ ] **Step 1: Write the test for RawSkill and Adapter protocol**

```python
# skill-index/tests/test_base.py
"""Tests for adapter base data structures."""
from __future__ import annotations

from adapters.base import RawSkill, SourceConfig, load_sources


class TestRawSkill:
    def test_create_raw_skill(self) -> None:
        skill = RawSkill(
            name="Test Skill",
            content="# Test\nSome content",
            source_path="skills/test.md",
            language="python",
            framework=None,
            categories=["testing"],
            description="A test skill",
            tags=["test"],
            updated_at="2026-03-28",
        )
        assert skill.name == "Test Skill"
        assert skill.language == "python"
        assert skill.framework is None
        assert skill.categories == ["testing"]


class TestSourceConfig:
    def test_create_source_config(self) -> None:
        config = SourceConfig(
            repo="anthropics/skills",
            adapter="anthropic_skills",
            trust="official",
            enabled=True,
        )
        assert config.repo == "anthropics/skills"
        assert config.trust == "official"

    def test_create_with_path_prefix(self) -> None:
        config = SourceConfig(
            repo="anthropics/claude-code",
            adapter="anthropic_plugins",
            trust="official",
            enabled=True,
            path_prefix="plugins",
        )
        assert config.path_prefix == "plugins"


class TestLoadSources:
    def test_load_sources_from_json(self, tmp_path) -> None:
        sources_file = tmp_path / "sources.json"
        sources_file.write_text(
            '{"sources": [{"repo": "anthropics/skills", "adapter": "anthropic_skills", '
            '"trust": "official", "enabled": true}]}'
        )
        configs = load_sources(sources_file)
        assert len(configs) == 1
        assert configs[0].repo == "anthropics/skills"

    def test_disabled_sources_excluded(self, tmp_path) -> None:
        sources_file = tmp_path / "sources.json"
        sources_file.write_text(
            '{"sources": ['
            '{"repo": "a/b", "adapter": "x", "trust": "official", "enabled": true},'
            '{"repo": "c/d", "adapter": "y", "trust": "community", "enabled": false}'
            ']}'
        )
        configs = load_sources(sources_file)
        assert len(configs) == 1
        assert configs[0].repo == "a/b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters'`

- [ ] **Step 3: Write the implementation**

```python
# skill-index/adapters/__init__.py
"""Adapter package for skill-index build pipeline."""
```

```python
# skill-index/adapters/base.py
"""Base data structures and protocol for source adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class RawSkill:
    """A skill extracted from a source before normalization."""

    name: str
    content: str
    source_path: str
    language: str
    framework: str | None
    categories: list[str]
    description: str
    tags: list[str] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class SourceConfig:
    """Configuration for a single source in sources.json."""

    repo: str
    adapter: str
    trust: str
    enabled: bool
    path_prefix: str = ""


class Adapter(Protocol):
    """Protocol that all source adapters must implement."""

    repo: str
    trust: str

    def crawl(self) -> list[RawSkill]: ...


def load_sources(path: Path) -> list[SourceConfig]:
    """Load and filter enabled sources from sources.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    configs: list[SourceConfig] = []
    for item in data["sources"]:
        config = SourceConfig(
            repo=item["repo"],
            adapter=item["adapter"],
            trust=item["trust"],
            enabled=item.get("enabled", True),
            path_prefix=item.get("path_prefix", ""),
        )
        if config.enabled:
            configs.append(config)
    return configs
```

```python
# skill-index/tests/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_base.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add adapters/ tests/
git commit -m "feat: adapter base protocol, RawSkill dataclass, source config loader"
```

---

### Task 2: GitHub API Helper and Category Classifier

**Files:**
- Create: `skill-index/adapters/github_api.py`
- Create: `skill-index/adapters/classifier.py`
- Create: `skill-index/tests/test_classifier.py`

- [ ] **Step 1: Write the classifier tests**

```python
# skill-index/tests/test_classifier.py
"""Tests for category classification and language detection."""
from __future__ import annotations

from adapters.classifier import classify_categories, detect_language_framework, slugify


class TestClassifyCategories:
    def test_testing_keywords(self) -> None:
        content = "Use pytest fixtures for setup. Write assertions with assert."
        cats = classify_categories(content)
        assert "testing" in cats

    def test_error_handling_keywords(self) -> None:
        content = "Catch exceptions with try/except. Raise ValueError for invalid input."
        cats = classify_categories(content)
        assert "error-handling" in cats

    def test_multiple_categories(self) -> None:
        content = (
            "Use snake_case naming conventions. "
            "Format code with ruff linter. "
            "Write tests with pytest."
        )
        cats = classify_categories(content)
        assert "naming-conventions" in cats
        assert "code-style" in cats
        assert "testing" in cats

    def test_fallback_when_no_match(self) -> None:
        content = "Hello world."
        cats = classify_categories(content)
        assert cats == ["architecture", "code-style"]

    def test_architecture_keywords(self) -> None:
        content = "Organize project structure with modules. Use dependency injection pattern."
        cats = classify_categories(content)
        assert "architecture" in cats


class TestDetectLanguageFramework:
    def test_nextjs(self) -> None:
        lang, fw = detect_language_framework("nextjs-cursorrules-prompt-file")
        assert lang == "typescript"
        assert fw == "next"

    def test_python_plain(self) -> None:
        lang, fw = detect_language_framework("python-cursorrules-prompt-file")
        assert lang == "python"
        assert fw is None

    def test_fastapi(self) -> None:
        lang, fw = detect_language_framework("fastapi-cursorrules-prompt-file")
        assert lang == "python"
        assert fw == "fastapi"

    def test_unknown_returns_none(self) -> None:
        lang, fw = detect_language_framework("unknown-thing")
        assert lang is None
        assert fw is None


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("Pytest Patterns") == "pytest-patterns"

    def test_special_chars(self) -> None:
        assert slugify("Next.js + React!") == "next-js-react"

    def test_leading_trailing(self) -> None:
        assert slugify("  --hello--  ") == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementations**

```python
# skill-index/adapters/github_api.py
"""GitHub API helpers for fetching repo trees and file contents."""
from __future__ import annotations

import json
import logging
import os
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
TIMEOUT = 15


def _headers() -> dict[str, str]:
    """Build request headers, including auth token if available."""
    headers = {"User-Agent": "skill-index-builder/1.0"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def get_tree(repo: str, path_prefix: str = "") -> list[dict]:
    """Fetch the file tree for a repo (or subdirectory).

    Returns a list of dicts with 'path' and 'type' keys.
    Uses the Git Trees API with recursive=1 for efficiency.
    """
    url = f"{GITHUB_API}/repos/{repo}/git/trees/HEAD?recursive=1"
    try:
        req = Request(url, headers=_headers())
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
        tree = data.get("tree", [])
        if path_prefix:
            prefix = path_prefix.rstrip("/") + "/"
            tree = [
                {**item, "path": item["path"][len(prefix):]}
                for item in tree
                if item["path"].startswith(prefix)
            ]
        return tree
    except Exception:
        logger.warning("Failed to fetch tree for %s", repo, exc_info=True)
        return []


def get_file(repo: str, path: str, branch: str = "main") -> str | None:
    """Fetch raw file content from a GitHub repo."""
    url = f"{GITHUB_RAW}/{repo}/{branch}/{path}"
    try:
        req = Request(url, headers=_headers())
        with urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        logger.debug("Failed to fetch %s/%s", repo, path, exc_info=True)
        return None


def raw_url(repo: str, path: str, branch: str = "main") -> str:
    """Construct the raw.githubusercontent.com URL for a file."""
    return f"{GITHUB_RAW}/{repo}/{branch}/{path}"
```

```python
# skill-index/adapters/classifier.py
"""Category classification and language/framework detection for unstructured content."""
from __future__ import annotations

import re

# Keyword → category mapping. Each keyword list is checked against lowercased content.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "naming-conventions": [
        "naming", "convention", "snake_case", "camelcase", "pascalcase",
        "variable name", "function name", "class name",
    ],
    "error-handling": [
        "error", "exception", "try", "catch", "except", "raise", "throw",
        "error handling", "error response",
    ],
    "testing": [
        "test", "spec", "assert", "mock", "fixture", "pytest", "jest",
        "vitest", "mocha", "unittest",
    ],
    "imports-and-dependencies": [
        "import", "require", "dependency", "module", "package",
        "from import", "import from",
    ],
    "documentation": [
        "docstring", "jsdoc", "comment", "documentation", "godoc",
        "type annotation", "type hint",
    ],
    "architecture": [
        "architect", "structure", "layout", "pattern", "directory",
        "module", "layer", "component", "service", "controller",
        "dependency injection", "middleware",
    ],
    "code-style": [
        "format", "lint", "style", "indent", "semicolon", "quote",
        "prettier", "eslint", "ruff", "black", "line length",
    ],
    "logging-and-observability": [
        "log", "logging", "trace", "tracing", "metric", "monitor",
        "observability", "structlog", "winston", "pino",
    ],
}

# Minimum keyword hits to assign a category.
CATEGORY_THRESHOLD = 2

# Folder name → (language, framework) mapping for awesome-cursorrules.
FOLDER_MAP: dict[str, tuple[str, str | None]] = {
    "nextjs": ("typescript", "next"),
    "next-js": ("typescript", "next"),
    "react": ("typescript", "react"),
    "react-native": ("typescript", "react-native"),
    "angular": ("typescript", "angular"),
    "vue": ("typescript", "vue"),
    "vuejs": ("typescript", "vue"),
    "svelte": ("typescript", "svelte"),
    "sveltekit": ("typescript", "svelte"),
    "typescript": ("typescript", None),
    "javascript": ("javascript", None),
    "nodejs": ("javascript", "node"),
    "node": ("javascript", "node"),
    "express": ("javascript", "express"),
    "nestjs": ("typescript", "nest"),
    "python": ("python", None),
    "django": ("python", "django"),
    "fastapi": ("python", "fastapi"),
    "flask": ("python", "flask"),
    "go": ("go", None),
    "golang": ("go", None),
    "gin": ("go", "gin"),
    "rust": ("rust", None),
    "actix": ("rust", "actix"),
    "tokio": ("rust", "tokio"),
    "java": ("java", None),
    "spring": ("java", "spring"),
    "spring-boot": ("java", "spring"),
    "kotlin": ("java", "kotlin"),
    "swift": ("any", "swift"),
    "swiftui": ("any", "swiftui"),
    "flutter": ("any", "flutter"),
    "dart": ("any", "dart"),
    "ruby": ("any", "ruby"),
    "rails": ("any", "rails"),
    "php": ("any", "php"),
    "laravel": ("any", "laravel"),
    "elixir": ("any", "elixir"),
    "c-sharp": ("any", "csharp"),
    "dotnet": ("any", "dotnet"),
}


def classify_categories(content: str) -> list[str]:
    """Classify content into skillgen categories using keyword matching.

    Returns a list of matching category slugs. Falls back to
    ["architecture", "code-style"] if no keywords match.
    """
    lower = content.lower()
    matched: list[str] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lower)
        if hits >= CATEGORY_THRESHOLD:
            matched.append(category)
    return matched if matched else ["architecture", "code-style"]


def detect_language_framework(folder_name: str) -> tuple[str | None, str | None]:
    """Detect language and framework from a folder name.

    Strips common suffixes like '-cursorrules-prompt-file' before lookup.
    Returns (language, framework) or (None, None) if not recognized.
    """
    # Strip known suffixes
    clean = folder_name.lower()
    for suffix in ["-cursorrules-prompt-file", "-cursor-rules", "-cursorrules", "-rules"]:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break

    result = FOLDER_MAP.get(clean)
    if result:
        return result
    return None, None


def slugify(name: str) -> str:
    """Convert a name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_classifier.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add adapters/github_api.py adapters/classifier.py tests/test_classifier.py
git commit -m "feat: GitHub API helper, category classifier, language/framework detection"
```

---

### Task 3: Cursorrules Adapter (Community Source)

**Files:**
- Create: `skill-index/adapters/cursorrules.py`
- Create: `skill-index/tests/test_cursorrules.py`

Starting with cursorrules because it's the largest source (179+ skills) and exercises the classifier heavily.

- [ ] **Step 1: Write the tests**

```python
# skill-index/tests/test_cursorrules.py
"""Tests for the awesome-cursorrules adapter."""
from __future__ import annotations

from unittest.mock import patch

from adapters.cursorrules import CursorrulesAdapter


class TestCursorrulesAdapter:
    def test_init(self) -> None:
        adapter = CursorrulesAdapter()
        assert adapter.repo == "PatrickJS/awesome-cursorrules"
        assert adapter.trust == "community"

    @patch("adapters.cursorrules.get_tree")
    @patch("adapters.cursorrules.get_file")
    def test_crawl_parses_folder_structure(self, mock_get_file, mock_get_tree) -> None:
        """Adapter correctly parses folder names and fetches .cursorrules files."""
        mock_get_tree.return_value = [
            {"path": "rules/nextjs-cursorrules-prompt-file/.cursorrules", "type": "blob"},
            {"path": "rules/python-cursorrules-prompt-file/.cursorrules", "type": "blob"},
            {"path": "rules/unknown-thing/.cursorrules", "type": "blob"},
            {"path": "README.md", "type": "blob"},  # should be skipped
        ]
        mock_get_file.side_effect = [
            "Use Server Components by default. Only use 'use client' when needed.",
            "Use snake_case for function names. Use pytest for testing.",
            "Some unknown content about coding.",
        ]

        adapter = CursorrulesAdapter()
        skills = adapter.crawl()

        # Should have 3 skills (unknown-thing still crawled, classified as "any")
        assert len(skills) == 3

        # First skill: nextjs
        nextjs = next(s for s in skills if "next" in s.name.lower() or s.framework == "next")
        assert nextjs.language == "typescript"
        assert nextjs.framework == "next"

        # Second skill: python
        python_skill = next(s for s in skills if s.language == "python")
        assert python_skill.framework is None

    @patch("adapters.cursorrules.get_tree")
    @patch("adapters.cursorrules.get_file")
    def test_crawl_skips_empty_content(self, mock_get_file, mock_get_tree) -> None:
        mock_get_tree.return_value = [
            {"path": "rules/python-cursorrules-prompt-file/.cursorrules", "type": "blob"},
        ]
        mock_get_file.return_value = None  # network failure
        adapter = CursorrulesAdapter()
        skills = adapter.crawl()
        assert len(skills) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_cursorrules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapters.cursorrules'`

- [ ] **Step 3: Write the implementation**

```python
# skill-index/adapters/cursorrules.py
"""Adapter for PatrickJS/awesome-cursorrules repository."""
from __future__ import annotations

import logging
import re

from adapters.base import RawSkill
from adapters.classifier import classify_categories, detect_language_framework, slugify
from adapters.github_api import get_file, get_tree, raw_url

logger = logging.getLogger(__name__)

REPO = "PatrickJS/awesome-cursorrules"


class CursorrulesAdapter:
    """Crawl awesome-cursorrules and extract skills from .cursorrules files."""

    repo = REPO
    trust = "community"

    def crawl(self) -> list[RawSkill]:
        """Fetch repo tree, find .cursorrules files, extract metadata."""
        tree = get_tree(self.repo)
        if not tree:
            logger.warning("Empty tree for %s", self.repo)
            return []

        # Find all .cursorrules files under rules/
        cursorrule_files = [
            item["path"]
            for item in tree
            if item["type"] == "blob"
            and item["path"].startswith("rules/")
            and item["path"].endswith(".cursorrules")
        ]

        skills: list[RawSkill] = []
        for file_path in cursorrule_files:
            # Extract folder name: rules/{folder-name}/.cursorrules
            match = re.match(r"rules/([^/]+)/", file_path)
            if not match:
                continue

            folder_name = match.group(1)
            language, framework = detect_language_framework(folder_name)

            content = get_file(self.repo, file_path)
            if not content:
                continue

            # Clean up the folder name for display
            display_name = folder_name.replace("-cursorrules-prompt-file", "")
            display_name = display_name.replace("-", " ").title()

            categories = classify_categories(content)

            skills.append(
                RawSkill(
                    name=f"{display_name} Cursor Rules",
                    content=content,
                    source_path=file_path,
                    language=language or "any",
                    framework=framework,
                    categories=categories,
                    description=f"Cursor rules for {display_name} development.",
                    tags=[slugify(display_name)],
                )
            )

        logger.info("Crawled %d skills from %s", len(skills), self.repo)
        return skills
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_cursorrules.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add adapters/cursorrules.py tests/test_cursorrules.py
git commit -m "feat: cursorrules adapter for PatrickJS/awesome-cursorrules"
```

---

### Task 4: Anthropic Skills Adapter (Official Source)

**Files:**
- Create: `skill-index/adapters/anthropic_skills.py`
- Create: `skill-index/tests/test_anthropic_skills.py`
- Create: `skill-index/requirements.txt`

- [ ] **Step 1: Write the tests**

```python
# skill-index/tests/test_anthropic_skills.py
"""Tests for the anthropics/skills adapter."""
from __future__ import annotations

from unittest.mock import patch

from adapters.anthropic_skills import AnthropicSkillsAdapter


SAMPLE_SKILL_MD = """---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces
license: Apache-2.0
---

# Frontend Design

Build high-quality web UIs with modern CSS and component patterns.

## Architecture
- Use component composition over inheritance
- Keep components focused and reusable
"""


class TestAnthropicSkillsAdapter:
    def test_init(self) -> None:
        adapter = AnthropicSkillsAdapter()
        assert adapter.repo == "anthropics/skills"
        assert adapter.trust == "official"

    @patch("adapters.anthropic_skills.get_tree")
    @patch("adapters.anthropic_skills.get_file")
    def test_crawl_parses_skill_md(self, mock_get_file, mock_get_tree) -> None:
        mock_get_tree.return_value = [
            {"path": "skills/frontend-design/SKILL.md", "type": "blob"},
            {"path": "skills/frontend-design/scripts/build.sh", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]
        mock_get_file.return_value = SAMPLE_SKILL_MD

        adapter = AnthropicSkillsAdapter()
        skills = adapter.crawl()

        assert len(skills) == 1
        skill = skills[0]
        assert skill.name == "frontend-design"
        assert "Create distinctive" in skill.description
        assert skill.language == "any"
        assert "architecture" in skill.categories

    @patch("adapters.anthropic_skills.get_tree")
    @patch("adapters.anthropic_skills.get_file")
    def test_crawl_skips_non_skill_dirs(self, mock_get_file, mock_get_tree) -> None:
        mock_get_tree.return_value = [
            {"path": "README.md", "type": "blob"},
            {"path": "LICENSE", "type": "blob"},
        ]

        adapter = AnthropicSkillsAdapter()
        skills = adapter.crawl()
        assert len(skills) == 0
        mock_get_file.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_anthropic_skills.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation and requirements.txt**

```
# skill-index/requirements.txt
pyyaml>=6.0
```

```python
# skill-index/adapters/anthropic_skills.py
"""Adapter for anthropics/skills repository (official Anthropic agent skills)."""
from __future__ import annotations

import logging
import re

import yaml

from adapters.base import RawSkill
from adapters.classifier import classify_categories
from adapters.github_api import get_file, get_tree, raw_url

logger = logging.getLogger(__name__)

REPO = "anthropics/skills"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body.

    Returns (metadata_dict, body_string). Returns ({}, content) if no frontmatter.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, content
    return metadata, match.group(2)


class AnthropicSkillsAdapter:
    """Crawl anthropics/skills and extract skills from SKILL.md files."""

    repo = REPO
    trust = "official"

    def crawl(self) -> list[RawSkill]:
        """Fetch repo tree, find SKILL.md files, parse frontmatter."""
        tree = get_tree(self.repo)
        if not tree:
            logger.warning("Empty tree for %s", self.repo)
            return []

        # Find all SKILL.md files under skills/
        skill_paths = [
            item["path"]
            for item in tree
            if item["type"] == "blob"
            and item["path"].startswith("skills/")
            and item["path"].endswith("/SKILL.md")
        ]

        skills: list[RawSkill] = []
        for path in skill_paths:
            content = get_file(self.repo, path)
            if not content:
                continue

            metadata, body = _parse_frontmatter(content)
            name = metadata.get("name", path.split("/")[-2])
            description = metadata.get("description", "")
            categories = classify_categories(body)

            skills.append(
                RawSkill(
                    name=name,
                    content=content,
                    source_path=path,
                    language="any",
                    framework=None,
                    categories=categories,
                    description=description,
                    tags=[name],
                )
            )

        logger.info("Crawled %d skills from %s", len(skills), self.repo)
        return skills
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && pip install pyyaml && python -m pytest tests/test_anthropic_skills.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add adapters/anthropic_skills.py tests/test_anthropic_skills.py requirements.txt
git commit -m "feat: anthropic_skills adapter for anthropics/skills (official)"
```

---

### Task 5: Copilot Instructions Adapter (Official Source)

**Files:**
- Create: `skill-index/adapters/copilot_instructions.py`
- Create: `skill-index/tests/test_copilot_instructions.py`

- [ ] **Step 1: Write the tests**

```python
# skill-index/tests/test_copilot_instructions.py
"""Tests for the github/awesome-copilot adapter."""
from __future__ import annotations

from unittest.mock import patch

from adapters.copilot_instructions import CopilotInstructionsAdapter


class TestCopilotInstructionsAdapter:
    def test_init(self) -> None:
        adapter = CopilotInstructionsAdapter()
        assert adapter.repo == "github/awesome-copilot"
        assert adapter.trust == "official"

    @patch("adapters.copilot_instructions.get_tree")
    @patch("adapters.copilot_instructions.get_file")
    def test_crawl_finds_markdown_instructions(self, mock_get_file, mock_get_tree) -> None:
        mock_get_tree.return_value = [
            {"path": "instructions/python/python.instructions.md", "type": "blob"},
            {"path": "instructions/csharp/csharp.instructions.md", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]
        mock_get_file.side_effect = [
            "# Python\nUse type hints. Use pytest for testing. Format with ruff.",
            "# C#\nUse async/await patterns. Follow .NET naming conventions.",
        ]

        adapter = CopilotInstructionsAdapter()
        skills = adapter.crawl()

        assert len(skills) == 2
        python_skill = next(s for s in skills if s.language == "python")
        assert python_skill.language == "python"
        assert "testing" in python_skill.categories or "code-style" in python_skill.categories

    @patch("adapters.copilot_instructions.get_tree")
    def test_crawl_handles_empty_tree(self, mock_get_tree) -> None:
        mock_get_tree.return_value = []
        adapter = CopilotInstructionsAdapter()
        skills = adapter.crawl()
        assert len(skills) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_copilot_instructions.py -v`
Expected: FAIL

- [ ] **Step 3: Write the implementation**

```python
# skill-index/adapters/copilot_instructions.py
"""Adapter for github/awesome-copilot repository (official GitHub copilot instructions)."""
from __future__ import annotations

import logging
import re

from adapters.base import RawSkill
from adapters.classifier import FOLDER_MAP, classify_categories, slugify
from adapters.github_api import get_file, get_tree

logger = logging.getLogger(__name__)

REPO = "github/awesome-copilot"

# Map directory names to (language, framework).
# awesome-copilot uses directory names like "python", "csharp", "react", etc.
COPILOT_LANG_MAP: dict[str, tuple[str, str | None]] = {
    **{k: v for k, v in FOLDER_MAP.items()},
    "csharp": ("any", "csharp"),
    "c-sharp": ("any", "csharp"),
    "bicep": ("any", "bicep"),
    "terraform": ("any", "terraform"),
    "docker": ("any", "docker"),
    "kubernetes": ("any", "kubernetes"),
    "github-actions": ("any", "github-actions"),
    "astro": ("typescript", "astro"),
    "blazor": ("any", "blazor"),
    "azure": ("any", "azure"),
}


class CopilotInstructionsAdapter:
    """Crawl github/awesome-copilot and extract instruction files."""

    repo = REPO
    trust = "official"

    def crawl(self) -> list[RawSkill]:
        """Fetch repo tree, find instruction markdown files."""
        tree = get_tree(self.repo)
        if not tree:
            logger.warning("Empty tree for %s", self.repo)
            return []

        # Find instruction files under instructions/
        instruction_paths = [
            item["path"]
            for item in tree
            if item["type"] == "blob"
            and item["path"].startswith("instructions/")
            and item["path"].endswith(".instructions.md")
        ]

        skills: list[RawSkill] = []
        for path in instruction_paths:
            # Extract language/tech from directory: instructions/{tech}/...
            match = re.match(r"instructions/([^/]+)/", path)
            if not match:
                continue

            tech_name = match.group(1)
            lang_fw = COPILOT_LANG_MAP.get(tech_name.lower())
            language = lang_fw[0] if lang_fw else "any"
            framework = lang_fw[1] if lang_fw else None

            content = get_file(self.repo, path)
            if not content:
                continue

            display_name = tech_name.replace("-", " ").title()
            categories = classify_categories(content)

            skills.append(
                RawSkill(
                    name=f"{display_name} Copilot Instructions",
                    content=content,
                    source_path=path,
                    language=language,
                    framework=framework,
                    categories=categories,
                    description=f"GitHub Copilot instructions for {display_name}.",
                    tags=[slugify(display_name), "copilot"],
                )
            )

        logger.info("Crawled %d skills from %s", len(skills), self.repo)
        return skills
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_copilot_instructions.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add adapters/copilot_instructions.py tests/test_copilot_instructions.py
git commit -m "feat: copilot_instructions adapter for github/awesome-copilot (official)"
```

---

### Task 6: Build Index Script and Sources Registry

**Files:**
- Create: `skill-index/build_index.py`
- Modify: `skill-index/sources.json` (replace hand-written version)
- Create: `skill-index/tests/test_build_index.py`

- [ ] **Step 1: Write the tests**

```python
# skill-index/tests/test_build_index.py
"""Tests for the index build pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from adapters.base import RawSkill
from build_index import build_index, deduplicate, raw_skill_to_index_entry


def _make_raw_skill(
    name: str = "Test Skill",
    language: str = "python",
    framework: str | None = None,
    source_path: str = "test.md",
) -> RawSkill:
    return RawSkill(
        name=name,
        content="# Test\nContent here.",
        source_path=source_path,
        language=language,
        framework=framework,
        categories=["testing"],
        description="A test skill.",
        tags=["test"],
        updated_at="2026-03-28",
    )


class TestRawSkillToIndexEntry:
    def test_converts_correctly(self) -> None:
        raw = _make_raw_skill()
        entry = raw_skill_to_index_entry(
            raw, source_repo="anthropics/skills", trust="official", source_prefix="anthropic"
        )
        assert entry["id"] == "anthropic-test-skill"
        assert entry["name"] == "Test Skill"
        assert entry["language"] == "python"
        assert entry["trust"] == "official"
        assert entry["source_repo"] == "anthropics/skills"
        assert "raw.githubusercontent.com" in entry["content_url"]
        assert entry["format"] == "markdown"


class TestDeduplicate:
    def test_keeps_highest_trust(self) -> None:
        entries = [
            {"id": "a-pytest", "name": "Pytest", "language": "python",
             "framework": None, "trust": "community", "source_repo": "a/b"},
            {"id": "b-pytest", "name": "Pytest", "language": "python",
             "framework": None, "trust": "official", "source_repo": "c/d"},
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["trust"] == "official"

    def test_different_languages_kept(self) -> None:
        entries = [
            {"id": "a-skill", "name": "Testing", "language": "python",
             "framework": None, "trust": "community", "source_repo": "a/b"},
            {"id": "b-skill", "name": "Testing", "language": "typescript",
             "framework": None, "trust": "community", "source_repo": "c/d"},
        ]
        result = deduplicate(entries)
        assert len(result) == 2

    def test_same_name_same_framework_deduped(self) -> None:
        entries = [
            {"id": "a-react", "name": "React", "language": "typescript",
             "framework": "react", "trust": "community", "source_repo": "a/b"},
            {"id": "b-react", "name": "React", "language": "typescript",
             "framework": "react", "trust": "community", "source_repo": "c/d"},
        ]
        result = deduplicate(entries)
        assert len(result) == 1


class TestBuildIndex:
    def test_build_writes_valid_json(self, tmp_path: Path) -> None:
        # Create a minimal sources.json with no enabled sources
        sources_file = tmp_path / "sources.json"
        sources_file.write_text('{"sources": []}')

        # Create contributed/ with one skill
        contributed_dir = tmp_path / "contributed"
        contributed_dir.mkdir()
        (contributed_dir / "custom-skill.md").write_text("# Custom\nMy custom skill.")

        output_file = tmp_path / "index.json"
        build_index(
            sources_file=sources_file,
            contributed_dir=contributed_dir,
            output_file=output_file,
        )

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["version"] == 2
        assert isinstance(data["skills"], list)
        assert len(data["skills"]) == 1
        assert data["skills"][0]["trust"] == "contributed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_build_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_index'`

- [ ] **Step 3: Write sources.json**

```json
{
  "sources": [
    {"repo": "anthropics/skills", "adapter": "anthropic_skills", "trust": "official", "enabled": true},
    {"repo": "github/awesome-copilot", "adapter": "copilot_instructions", "trust": "official", "enabled": true},
    {"repo": "PatrickJS/awesome-cursorrules", "adapter": "cursorrules", "trust": "community", "enabled": true}
  ]
}
```

- [ ] **Step 4: Write build_index.py**

```python
#!/usr/bin/env python3
"""Build the skill index by crawling trusted sources and merging results."""
from __future__ import annotations

import importlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from adapters.base import RawSkill, load_sources
from adapters.classifier import classify_categories, slugify
from adapters.github_api import raw_url

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TRUST_ORDER = {"official": 0, "community": 1, "contributed": 2}

# Map adapter names to module.ClassName
ADAPTER_REGISTRY: dict[str, tuple[str, str]] = {
    "anthropic_skills": ("adapters.anthropic_skills", "AnthropicSkillsAdapter"),
    "copilot_instructions": ("adapters.copilot_instructions", "CopilotInstructionsAdapter"),
    "cursorrules": ("adapters.cursorrules", "CursorrulesAdapter"),
}


def raw_skill_to_index_entry(
    raw: RawSkill,
    source_repo: str,
    trust: str,
    source_prefix: str,
) -> dict:
    """Convert a RawSkill into an index.json entry dict."""
    return {
        "id": f"{source_prefix}-{slugify(raw.name)}",
        "name": raw.name,
        "language": raw.language,
        "framework": raw.framework,
        "categories": raw.categories,
        "description": raw.description,
        "source_repo": source_repo,
        "source_path": raw.source_path,
        "content_url": raw_url(source_repo, raw.source_path),
        "trust": trust,
        "format": "markdown",
        "tags": raw.tags,
        "updated_at": raw.updated_at,
    }


def deduplicate(entries: list[dict]) -> list[dict]:
    """Deduplicate by (language, framework, name). Keep highest trust."""
    seen: dict[tuple, dict] = {}
    for entry in entries:
        key = (
            entry.get("language", "").lower(),
            (entry.get("framework") or "").lower(),
            entry.get("name", "").lower(),
        )
        existing = seen.get(key)
        if existing is None:
            seen[key] = entry
        else:
            # Keep higher trust (lower order number)
            existing_rank = TRUST_ORDER.get(existing["trust"], 99)
            new_rank = TRUST_ORDER.get(entry["trust"], 99)
            if new_rank < existing_rank:
                seen[key] = entry
    return list(seen.values())


def _load_contributed(contributed_dir: Path) -> list[dict]:
    """Load manually contributed skills from contributed/*.md."""
    entries: list[dict] = []
    if not contributed_dir.is_dir():
        return entries
    for md_file in sorted(contributed_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        name = md_file.stem.replace("-", " ").title()
        categories = classify_categories(content)
        entries.append({
            "id": f"contributed-{slugify(name)}",
            "name": name,
            "language": "any",
            "framework": None,
            "categories": categories,
            "description": f"Community-contributed skill: {name}.",
            "source_repo": "",
            "source_path": f"contributed/{md_file.name}",
            "content_url": "",
            "trust": "contributed",
            "format": "markdown",
            "tags": [],
            "updated_at": "",
        })
    return entries


def build_index(
    sources_file: Path | None = None,
    contributed_dir: Path | None = None,
    output_file: Path | None = None,
) -> None:
    """Main build pipeline: load sources, run adapters, dedupe, write index."""
    root = Path(__file__).parent
    sources_file = sources_file or root / "sources.json"
    contributed_dir = contributed_dir or root / "contributed"
    output_file = output_file or root / "index.json"

    configs = load_sources(sources_file)
    all_entries: list[dict] = []
    sources_crawled: list[str] = []

    for config in configs:
        adapter_info = ADAPTER_REGISTRY.get(config.adapter)
        if adapter_info is None:
            logger.warning("Unknown adapter: %s (skipping %s)", config.adapter, config.repo)
            continue

        module_name, class_name = adapter_info
        try:
            module = importlib.import_module(module_name)
            adapter_class = getattr(module, class_name)
            adapter = adapter_class()
            raw_skills = adapter.crawl()
        except Exception:
            logger.warning("Adapter %s failed for %s", config.adapter, config.repo, exc_info=True)
            continue

        source_prefix = config.repo.split("/")[-1].lower().replace("-", "")
        for raw in raw_skills:
            entry = raw_skill_to_index_entry(raw, config.repo, config.trust, source_prefix)
            all_entries.append(entry)

        sources_crawled.append(config.repo)
        logger.info("  %s: %d skills", config.repo, len(raw_skills))

    # Add contributed skills
    contributed = _load_contributed(contributed_dir)
    all_entries.extend(contributed)

    # Deduplicate
    deduped = deduplicate(all_entries)

    # Sort: official first, then community, then contributed
    deduped.sort(key=lambda e: (TRUST_ORDER.get(e["trust"], 99), e["name"].lower()))

    # Count by trust
    counts = {}
    for e in deduped:
        counts[e["trust"]] = counts.get(e["trust"], 0) + 1

    index = {
        "version": 2,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources_crawled": sources_crawled,
        "skills": deduped,
    }

    output_file.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")

    stats_parts = [f"{v} {k}" for k, v in sorted(counts.items(), key=lambda x: TRUST_ORDER.get(x[0], 99))]
    logger.info(
        "Built index: %d skills from %d sources (%s)",
        len(deduped), len(sources_crawled), ", ".join(stats_parts),
    )


if __name__ == "__main__":
    build_index()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -m pytest tests/test_build_index.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add build_index.py sources.json tests/test_build_index.py
git commit -m "feat: build_index.py pipeline with dedup, contributed skills, sources registry"
```

---

### Task 7: CI Workflow and Initial Index Build

**Files:**
- Create: `skill-index/.github/workflows/rebuild-index.yml`
- Modify: `skill-index/contributed/` (move existing hand-written skills)
- Modify: `skill-index/README.md`

- [ ] **Step 1: Create the CI workflow**

```yaml
# skill-index/.github/workflows/rebuild-index.yml
name: Rebuild Index

on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Build index
        run: python build_index.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Commit if changed
        run: |
          git diff --quiet index.json && echo "No changes" && exit 0
          git config user.name "skill-index-bot"
          git config user.email "bot@skillgen.dev"
          git add index.json
          git commit -m "chore: rebuild index ($(date -u +%Y-%m-%d))"
          git push
```

- [ ] **Step 2: Move existing hand-written skills to contributed/**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
mkdir -p contributed
mv skills/python/*.md contributed/ 2>/dev/null || true
mv skills/typescript/*.md contributed/ 2>/dev/null || true
mv skills/javascript/*.md contributed/ 2>/dev/null || true
mv skills/go/*.md contributed/ 2>/dev/null || true
mv skills/rust/*.md contributed/ 2>/dev/null || true
mv skills/java/*.md contributed/ 2>/dev/null || true
rm -rf skills/
```

- [ ] **Step 3: Run the build locally to generate the initial index**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python build_index.py`
Expected: Output showing skills crawled from each source + contributed skills. `index.json` updated with v2 format.

Note: This step requires network access to GitHub. If sources are unreachable (rate limits, etc.), the index will contain only contributed skills. That's fine — CI will populate the rest on first run.

- [ ] **Step 4: Verify the generated index**

Run: `cd /home/mmoselhy/projects/skillgen/skill-index && python -c "import json; d=json.load(open('index.json')); print(f'v{d[\"version\"]}: {len(d[\"skills\"])} skills')"`
Expected: `v2: N skills` (where N depends on network results + 15 contributed)

- [ ] **Step 5: Commit**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git add -A
git commit -m "feat: CI workflow, migrate hand-written skills to contributed/, initial v2 index"
```

- [ ] **Step 6: Push to GitHub**

```bash
cd /home/mmoselhy/projects/skillgen/skill-index
git push origin main
```

---

## Phase 2: Client Changes (skillgen package)

All Phase 2 tasks are in `/home/mmoselhy/projects/skillgen/`.

---

### Task 8: Update IndexEntry Model with v2 Fields

**Files:**
- Modify: `skillgen/models.py:287-298`
- Modify: `tests/test_enricher.py:83-101`

- [ ] **Step 1: Write the test for v2 IndexEntry**

Add a new test to `tests/test_enricher.py` after the existing `_make_index_entry` helper. First, update the helper to support v2 fields:

Replace `_make_index_entry` in `tests/test_enricher.py:83-101` with:

```python
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
```

Add a new test class after `TestSlugify`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py::TestIndexEntryV2 -v`
Expected: FAIL with `TypeError: IndexEntry.__init__() got an unexpected keyword argument 'source_repo'`

- [ ] **Step 3: Update IndexEntry in models.py**

Replace `IndexEntry` in `skillgen/models.py:287-298`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py::TestIndexEntryV2 -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Verify existing tests still pass**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py -v`
Expected: All existing tests PASS (v2 fields have defaults, so v1 usage is unchanged)

- [ ] **Step 6: Commit**

```bash
cd /home/mmoselhy/projects/skillgen
git add skillgen/models.py tests/test_enricher.py
git commit -m "feat: add v2 fields to IndexEntry (source_repo, trust, content_url, format, tags)"
```

---

### Task 9: Update _parse_index for v2 and Add Trust Filtering

**Files:**
- Modify: `skillgen/enricher.py:88-126` (`_parse_index`)
- Modify: `skillgen/enricher.py:179-227` (`_match_entries`)
- Modify: `tests/test_enricher.py`

- [ ] **Step 1: Write tests for v2 parsing and trust filtering**

Add to `tests/test_enricher.py`:

```python
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

        content = json.dumps([{
            "id": "old-skill",
            "name": "Old Skill",
            "language": "python",
            "categories": ["testing"],
            "path": "old.md",
            "description": "Legacy",
        }])
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py::TestParseIndexV2 tests/test_enricher.py::TestTrustFiltering -v`
Expected: FAIL (TestParseIndexV2 — missing v2 field parsing; TestTrustFiltering — `_match_entries` doesn't accept `trust_filter`)

- [ ] **Step 3: Update _parse_index in enricher.py**

Replace the entry construction block in `_parse_index` (inside the `for item in items:` loop, `skillgen/enricher.py:109-125`):

```python
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
                source_repo=str(item.get("source_repo", "")),
                content_url=str(item.get("content_url", "")),
                trust=str(item.get("trust", "contributed")),
                format=str(item.get("format", "markdown")),
                tags=[str(t) for t in item.get("tags", [])],
                updated_at=str(item.get("updated_at", "")),
            )
            entries.append(entry)
        except (KeyError, TypeError):
            logger.debug("Skipping malformed index entry: %s", item)
            continue

    return entries
```

- [ ] **Step 4: Update _match_entries to accept trust_filter**

Replace the `_match_entries` signature and add trust filtering at the top of the function body (`skillgen/enricher.py:179-227`):

```python
def _match_entries(
    entries: list[IndexEntry],
    conventions: ProjectConventions,
    trust_filter: set[str] | None = None,
) -> tuple[list[IndexEntry], list[str]]:
    """Match index entries against project conventions.

    Matching rules:
    - Trust filter applied first (if provided).
    - Language must match (required).
    - Framework must match if set on the entry.
    - Entries whose categories are ALL already covered locally are skipped.

    Returns (matched_entries, skipped_category_names).
    """
    # Apply trust filter first.
    if trust_filter:
        entries = [e for e in entries if e.trust in trust_filter]

    # Gather project languages (lowercase).
    project_languages: set[str] = set()
    for lang_info in conventions.project_info.languages:
        project_languages.add(lang_info.language.value.lower())

    # Also match "any" language entries.
    project_languages.add("any")

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py -v`
Expected: ALL tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
cd /home/mmoselhy/projects/skillgen
git add skillgen/enricher.py tests/test_enricher.py
git commit -m "feat: v2 index parsing with trust filtering in _match_entries"
```

---

### Task 10: Update Content Fetching and Formatting for v2

**Files:**
- Modify: `skillgen/enricher.py:250-298` (`_fetch_skill_content`, `_format_community_claude`, `_format_community_cursor`)

- [ ] **Step 1: Write tests for content_url and new header format**

Add to `tests/test_enricher.py`:

```python
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
        # Verify it used the content_url, not BASE_URL + path
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py::TestV2ContentFetching tests/test_enricher.py::TestV2Formatting -v`
Expected: FAIL (`_fetch_skill_content` doesn't accept `content_url` parameter)

- [ ] **Step 3: Update _fetch_skill_content**

Replace `_fetch_skill_content` in `skillgen/enricher.py:250-276`:

```python
def _fetch_skill_content(
    path: str,
    content_url: str = "",
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> str | None:
    """Fetch a single skill markdown file.

    Uses content_url if available (v2 index), falls back to BASE_URL + path (v1).
    Returns the file content as a string, or None on failure.
    """
    resolved_cache_dir = _get_cache_dir(cache_dir)
    cache_filename = path.replace("/", "_")

    # Try fresh cache.
    if not no_cache:
        cached = _read_cache(resolved_cache_dir, cache_filename, CACHE_TTL_SECONDS)
        if cached is not None:
            return cached

    # Determine URL: prefer content_url (v2), fall back to BASE_URL + path (v1).
    url = content_url if content_url else BASE_URL + path
    raw = _fetch_url(url)
    if raw is not None:
        content = raw.decode("utf-8")
        _write_cache(resolved_cache_dir, cache_filename, content)
        return content

    return None
```

- [ ] **Step 4: Update _format_community_claude and _format_community_cursor**

Replace `_format_community_claude` in `skillgen/enricher.py:290-298`:

```python
def _format_community_claude(entry: IndexEntry, content: str) -> str:
    """Format a community skill for .claude/skills/community/*.md."""
    source = entry.source_repo or f"{BASE_URL}{entry.path}"
    lines = [
        f"<!-- Community skill: {entry.name} (id: {entry.id}) -->",
        f"<!-- Source: {source} | Trust: {entry.trust} -->",
        "",
        content,
    ]
    return "\n".join(lines)
```

Replace `_format_community_cursor` in `skillgen/enricher.py:301-315`:

```python
def _format_community_cursor(entry: IndexEntry, content: str) -> str:
    """Format a community skill for .cursor/rules/community/*.mdc."""
    source = entry.source_repo or f"{BASE_URL}{entry.path}"
    lines = [
        "---",
        f"description: {entry.description}",
        "globs: *",
        "alwaysApply: false",
        "---",
        "",
        f"<!-- Community skill: {entry.name} (id: {entry.id}) -->",
        f"<!-- Source: {source} | Trust: {entry.trust} -->",
        "",
        content,
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Update the `apply` function to pass content_url**

In `skillgen/enricher.py`, update the `apply` function's call to `_fetch_skill_content` (around line 347):

```python
        content = _fetch_skill_content(
            entry.path,
            content_url=entry.content_url,
            cache_dir=cache_dir,
            no_cache=no_cache,
        )
```

- [ ] **Step 6: Run all enricher tests**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/test_enricher.py -v`
Expected: ALL tests PASS

- [ ] **Step 7: Commit**

```bash
cd /home/mmoselhy/projects/skillgen
git add skillgen/enricher.py tests/test_enricher.py
git commit -m "feat: v2 content fetching with content_url, trust in file headers"
```

---

### Task 11: Add --trust CLI Flag and Update Renderer

**Files:**
- Modify: `skillgen/cli.py:127-146` (add `--trust` flag)
- Modify: `skillgen/cli.py:258-266` (pass trust to search)
- Modify: `skillgen/enricher.py:230-244` (`search` function)
- Modify: `skillgen/renderer.py:189-226` (add Trust and Source columns)

- [ ] **Step 1: Add --trust flag to cli.py**

After the `no_cache` option (line 146), add:

```python
    trust: str | None = typer.Option(
        None,
        "--trust",
        help="Filter by trust tier: official, community, contributed, or all. Default: all.",
    ),
```

- [ ] **Step 2: Add trust validation and parsing in cli.py**

After the `pick_indices` validation block (around line 194), add:

```python
    trust_filter: set[str] | None = None
    if trust is not None:
        valid_tiers = {"official", "community", "contributed", "all"}
        if trust.lower() not in valid_tiers:
            _console.print(
                f"[red]Error:[/red] --trust must be one of: official, community, contributed, all."
            )
            raise typer.Exit(code=1)
        if trust.lower() != "all":
            trust_filter = {trust.lower()}
```

- [ ] **Step 3: Pass trust_filter to enrich_search**

Update the `enrich_search` call in `cli.py` (around line 263):

```python
                enrich_result = enrich_search(
                    conventions, cache_dir=None, no_cache=no_cache,
                    trust_filter=trust_filter,
                )
```

- [ ] **Step 4: Update search() in enricher.py to accept trust_filter**

Replace the `search` function in `skillgen/enricher.py:230-244`:

```python
def search(
    conventions: ProjectConventions,
    cache_dir: Path | None = None,
    no_cache: bool = False,
    trust_filter: set[str] | None = None,
) -> EnrichmentResult:
    """Fetch the skill index and match entries against project conventions."""
    errors: list[str] = []

    entries = _fetch_index(cache_dir=cache_dir, no_cache=no_cache)
    if not entries:
        errors.append("Could not fetch or parse the skill index.")
        return EnrichmentResult(matched=[], skipped_categories=[], errors=errors)

    matched, skipped = _match_entries(entries, conventions, trust_filter=trust_filter)
    return EnrichmentResult(matched=matched, skipped_categories=skipped, errors=errors)
```

- [ ] **Step 5: Update render_enrich_preview in renderer.py**

Replace `render_enrich_preview` in `skillgen/renderer.py:189-226`:

```python
def render_enrich_preview(result: EnrichmentResult) -> None:
    """Show a Rich table when --enrich is used without --apply."""
    if not result.matched and result.errors:
        console.print(f"\n[yellow]Warning:[/yellow] {result.errors[0]}")
        return
    if not result.matched:
        console.print("\n[dim]No community skills found.[/dim]")
        return

    table = Table(
        title="Community Skills Matching This Project",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="bold", justify="right")
    table.add_column("Trust", style="yellow", min_width=10)
    table.add_column("Skill", style="cyan", min_width=20)
    table.add_column("Categories", style="green")
    table.add_column("Source", style="dim")

    for idx, entry in enumerate(result.matched, start=1):
        categories = ", ".join(entry.categories)
        source = entry.source_repo or "—"
        table.add_row(str(idx), entry.trust, entry.name, categories, source)

    console.print()
    console.print(table)

    if result.skipped_categories:
        console.print(
            f"\n[dim]Skipped (already covered locally): "
            f"{', '.join(result.skipped_categories)}[/dim]"
        )

    console.print(
        "\n[bold]To install:[/bold]  skillgen . --enrich --apply"
    )
    console.print(
        "[bold]To filter:[/bold]   skillgen . --enrich --trust official"
    )
    console.print(
        "[bold]To pick:[/bold]     skillgen . --enrich --apply --pick 1,2"
    )
```

- [ ] **Step 6: Run all tests**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/ -v`
Expected: ALL tests PASS

- [ ] **Step 7: Commit**

```bash
cd /home/mmoselhy/projects/skillgen
git add skillgen/cli.py skillgen/enricher.py skillgen/renderer.py
git commit -m "feat: --trust CLI flag, trust/source columns in enrich preview"
```

---

## Phase 3: Skill File Updates

---

### Task 12: Update /skillgen enrich Skill and Reference Files

**Files:**
- Modify: `.claude/skills/skillgen/enrich.md`
- Modify: `.claude/skills/skillgen/SKILL.md` (Community Enrichment section)

- [ ] **Step 1: Update enrich.md with v2 schema**

Replace the content of `.claude/skills/skillgen/enrich.md`:

```markdown
# Community Enrichment — Supporting Reference

## Index URL

`https://raw.githubusercontent.com/mmoselhy/skill-index/main/index.json`

## Index JSON Schema (v2)

```json
{
  "version": 2,
  "updated": "2026-03-28T04:30:00Z",
  "sources_crawled": ["anthropics/skills", "PatrickJS/awesome-cursorrules"],
  "skills": [
    {
      "id": "anthropic-frontend-design",
      "name": "Frontend Design",
      "language": "any",
      "framework": null,
      "categories": ["architecture", "code-style"],
      "description": "Create distinctive, production-grade frontend interfaces.",
      "source_repo": "anthropics/skills",
      "source_path": "skills/frontend-design/SKILL.md",
      "content_url": "https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md",
      "trust": "official",
      "format": "skill-md",
      "tags": ["frontend", "design"],
      "updated_at": "2026-03-15"
    }
  ]
}
```

## Fields

- `id` — unique slug
- `name` — display name
- `language` — python/typescript/javascript/go/rust/java/any
- `framework` — string or null
- `categories` — array matching local skill filenames without .md
- `description` — one-line summary
- `source_repo` — GitHub owner/repo where the skill originates
- `source_path` — path within the source repo
- `content_url` — direct raw URL to fetch content
- `trust` — `official`, `community`, or `contributed`
- `format` — `skill-md`, `cursorrules`, `copilot-instructions`, `claude-md`, `markdown`
- `tags` — freeform search tags
- `updated_at` — ISO date of last source modification

## Trust Tiers

| Tier | Label | Sources |
|---|---|---|
| 1 | `official` | anthropics/skills, anthropics/claude-code/plugins, github/awesome-copilot |
| 2 | `community` | PatrickJS/awesome-cursorrules, josix/awesome-claude-md |
| 3 | `contributed` | User-submitted via PR to skill-index repo |

## Skill Content URL

Each skill has a `content_url` field pointing directly to the raw file in the source repo. Use this URL to fetch content. If `content_url` is empty (v1 entries), fall back to: `https://raw.githubusercontent.com/mmoselhy/skill-index/main/{path}`
```

- [ ] **Step 2: Update SKILL.md Community Enrichment section**

In `.claude/skills/skillgen/SKILL.md`, find the `### Step 5: Present candidates to user` section and update the example output to include trust and source:

Find the example output block and replace it with:

```
Community skills available for Python:

  1. [+] Frontend Design — Create distinctive, production-grade frontend interfaces
       Source: anthropics/skills (official)
       Fills gap: No frontend conventions detected locally.

  2. [✓] Python Pytest Rules — Fixture patterns, parametrize, conftest organization
       Source: PatrickJS/awesome-cursorrules (community)
       Aligns: Project already uses pytest with similar fixture patterns.

  3. [!] Python Import Style — Absolute imports with isort grouping
       Source: github/awesome-copilot (official)
       Conflicts: Project uses 89% absolute imports but different isort config.

Install which? (1,2,3 / all / none):
```

Also update `### Step 6: Install selected skills` to use the new header format:

```markdown
<!-- Community skill: {name} (id: {id}) -->
<!-- Source: {source_repo} | Trust: {trust} -->

{original skill content}
```

- [ ] **Step 3: Commit**

```bash
cd /home/mmoselhy/projects/skillgen
git add .claude/skills/skillgen/enrich.md .claude/skills/skillgen/SKILL.md
git commit -m "docs: update /skillgen enrich skill for v2 index with trust tiers"
```

---

### Task 13: Final Integration Test

**Files:** None (verification only)

- [ ] **Step 1: Verify skill-index serves v2 format**

Run: `curl -sf https://raw.githubusercontent.com/mmoselhy/skill-index/main/index.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'v{d.get(\"version\",1)}: {len(d[\"skills\"])} skills')" `

Expected: `v2: N skills`

- [ ] **Step 2: Run the full test suite**

Run: `cd /home/mmoselhy/projects/skillgen && python -m pytest tests/ -v`
Expected: ALL tests PASS

- [ ] **Step 3: Manual smoke test of --enrich**

Run: `cd /home/mmoselhy/projects/skillgen && skillgen . --enrich`
Expected: Table with Trust and Source columns, skills from multiple sources

- [ ] **Step 4: Manual smoke test of --trust filter**

Run: `cd /home/mmoselhy/projects/skillgen && skillgen . --enrich --trust official`
Expected: Only skills with `trust: official` shown

- [ ] **Step 5: Manual smoke test of --enrich --apply**

Run: `cd /home/mmoselhy/projects/skillgen && skillgen . --enrich --apply --pick 1 --dry-run`
Expected: Shows what would be installed with the new header format including trust and source
