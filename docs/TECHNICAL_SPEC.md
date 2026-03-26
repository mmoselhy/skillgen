# skillgen -- Technical Specification

**Version:** 1.0
**Date:** 2026-03-24
**Status:** Draft
**Author:** Architecture Team

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Module Breakdown](#2-module-breakdown)
3. [Data Flow](#3-data-flow)
4. [Key Data Structures](#4-key-data-structures)
5. [External Dependencies](#5-external-dependencies)
6. [LLM Prompt Templates](#6-llm-prompt-templates)
7. [File Output Format Specs](#7-file-output-format-specs)
8. [Error Handling Strategy](#8-error-handling-strategy)
9. [Testing Strategy](#9-testing-strategy)

---

## 1. High-Level Architecture

```
                            skillgen Architecture
                            =====================

  User
   |
   v
+------------------------------------------------------------------+
|  cli.py (Typer)                                                  |
|  - Parses args: <path>, --format, --diff, --dry-run, etc.       |
|  - Validates input path                                          |
|  - Orchestrates pipeline                                         |
+------------------------------------------------------------------+
   |
   | ProjectPath
   v
+------------------------------------------------------------------+
|  detector.py                                                     |
|  - Walks file tree (respects .gitignore, skips vendored dirs)    |
|  - Counts file extensions                                        |
|  - Reads package manifests & config files                        |
|  - Identifies frameworks from markers                            |
|  Output: ProjectInfo                                             |
+------------------------------------------------------------------+
   |
   | ProjectInfo
   v
+------------------------------------------------------------------+
|  analyzer.py                                                     |
|  - Selects representative file sample (min(30, 20% of files))   |
|  - AST parsing via tree-sitter (per-language grammars)           |
|  - Regex fallback when tree-sitter unavailable/fails             |
|  - Extracts patterns across 8 categories                        |
|  - Computes confidence scores & detects conflicts                |
|  Output: AnalysisResult                                          |
+------------------------------------------------------------------+
   |
   | AnalysisResult
   v
+------------------------------------------------------------------+
|  generator.py                                                    |
|  - LOCAL MODE (default): Rule-based template engine              |
|    - Renders skill content from patterns + Jinja-like templates  |
|  - LLM MODE (--llm flag): Provider-agnostic LLM generation      |
|    - Anthropic SDK (Claude) or OpenAI SDK (GPT-4)                |
|    - Sends analysis data + prompt templates to LLM               |
|    - Falls back to LOCAL MODE on failure                         |
|  - Filters skills with < 3 patterns (skip threshold)            |
|  Output: GenerationResult                                        |
+------------------------------------------------------------------+
   |
   | GenerationResult
   v
+------------------------------------------------------------------+
|  writer.py                                                       |
|  - Writes .claude/skills/*.md  (if format=claude|all)            |
|  - Writes .cursor/rules/*.mdc  (if format=cursor|all)            |
|  - Writes/appends AGENTS.md    (if format=all)                   |
|  - Atomic writes (temp file + rename)                            |
|  - Cleans up orphaned skill files from previous runs             |
|  - Respects --dry-run (prints to stdout instead)                 |
|  Output: list[WrittenFile]                                       |
+------------------------------------------------------------------+
   |
   | list[WrittenFile]
   v
+------------------------------------------------------------------+
|  renderer.py (Rich)                                              |
|  - Spinner during each pipeline phase                            |
|  - Summary table: file path, format, line count                  |
|  - --diff mode: comparison table with colorized output           |
|  - --verbose: detailed analysis steps                            |
|  - --quiet: suppress all except errors                           |
|  Output: terminal display                                        |
+------------------------------------------------------------------+


  Data Flow Summary (left to right):

  path --> [detector] --> ProjectInfo --> [analyzer] --> AnalysisResult
       --> [generator] --> GenerationResult --> [writer] --> WrittenFile[]
       --> [renderer] --> terminal output


  Shared across all modules:

+------------------------------------------------------------------+
|  models.py                                                       |
|  - ProjectInfo, CodePattern, SkillDefinition, AnalysisResult,    |
|    GenerationResult, WrittenFile, SkillCategory (enum)           |
|  - All defined as Python dataclasses                             |
+------------------------------------------------------------------+
```

### Pipeline Flow Diagram

```
                 +-------+
                 | START |
                 +---+---+
                     |
                     v
            +--------+--------+
            | Validate path   |
            | (cli.py)        |
            +--------+--------+
                     |
          +----------+-----------+
          | Is valid directory?  |
          +----------+-----------+
           No |            | Yes
              v            v
        Exit code 1   +---+---+
                       | Scan  |  <-- respects .gitignore
                       | files |      skips vendored dirs
                       +---+---+
                           |
                           v
                   +-------+-------+
                   | Detect langs  |
                   | & frameworks  |
                   | (detector.py) |
                   +-------+-------+
                           |
              +------------+------------+
              | Any supported language? |
              +------------+------------+
               No |              | Yes
                  v              v
            Exit code 1   +-----+------+
            "No supported  | Sample     |
             language"     | files for  |
                           | analysis   |
                           +-----+------+
                                 |
                                 v
                         +-------+-------+
                         | AST + regex   |
                         | pattern       |
                         | extraction    |
                         | (analyzer.py) |
                         +-------+-------+
                                 |
                                 v
                    +------------+-------------+
                    | --llm flag provided?     |
                    +------------+-------------+
                     No |              | Yes
                        v              v
                  +-----+-----+  +----+------+
                  | Rule-based |  | LLM-based |
                  | generation |  | generation|
                  +-----+-----+  +----+------+
                        |              |
                        +------+-------+
                               |
                               v
                       +-------+-------+
                       | Filter skills |
                       | (>= 3 pats)  |
                       +-------+-------+
                               |
                               v
                  +------------+-------------+
                  | --dry-run?               |
                  +------------+-------------+
                   Yes |             | No
                       v             v
                 Print to      +-----+-----+
                 stdout        | Write      |
                               | files      |
                               | (writer.py)|
                               +-----+-----+
                                     |
                                     v
                              +------+------+
                              | Render      |
                              | summary     |
                              | (renderer)  |
                              +------+------+
                                     |
                                     v
                                 +---+---+
                                 |  END  |
                                 | (0)   |
                                 +-------+
```

---

## 2. Module Breakdown

### 2.1 `cli.py` -- Entry Point and Argument Parsing

**Responsibility:** Defines the Typer application, parses all CLI arguments and flags, validates the input path, orchestrates the pipeline by calling detector -> analyzer -> generator -> writer -> renderer in sequence, and manages exit codes.

**Key design decisions:**
- Uses `typer` for CLI framework (automatic `--help` generation, type validation, shell completion).
- The main function is synchronous. Parallelism happens inside individual modules (e.g., file scanning in detector).
- Catches all exceptions at the top level to guarantee exit code 2 on internal errors.

```python
# cli.py

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from skillgen.detector import detect_project
from skillgen.analyzer import analyze_project
from skillgen.generator import generate_skills, GenerationMode
from skillgen.writer import write_skills
from skillgen.renderer import (
    render_summary,
    render_diff,
    render_dry_run,
    create_progress,
)
from skillgen.models import OutputFormat

app = typer.Typer(
    name="skillgen",
    help="Analyze a codebase and generate AI agent skill files.",
    add_completion=True,
    no_args_is_help=False,
)
console = Console()

__version__ = "1.0.0"


def version_callback(value: bool) -> None:
    if value:
        console.print(f"skillgen {__version__}")
        raise typer.Exit()


@app.command()
def main(
    path: Path = typer.Argument(
        ".",
        help="Path to the codebase to analyze.",
        exists=False,  # We validate manually for better error messages.
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.ALL,
        "--format",
        "-f",
        help="Target AI tool format.",
    ),
    diff: bool = typer.Option(
        False, "--diff", help="Show what the AI agent learns vs. blank-slate."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview generated files without writing to disk."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed analysis steps."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress all output except errors."
    ),
    llm: bool = typer.Option(
        False, "--llm", help="Use LLM for enhanced skill generation."
    ),
    llm_provider: Optional[str] = typer.Option(
        None,
        "--llm-provider",
        help="LLM provider: 'anthropic' or 'openai'. Default: auto-detect from env.",
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", callback=version_callback, is_eager=True,
    ),
) -> None:
    """
    Analyze a codebase and generate AI agent skill files.

    Example:
        skillgen ./my-project
        skillgen ./my-project --format claude --dry-run
        skillgen . --diff --verbose
    """
    # --- Path validation ---
    resolved = path.resolve()
    if not resolved.exists():
        console.print(f"[red]Error:[/red] {path} does not exist.")
        raise typer.Exit(code=1)
    if resolved.is_file():
        console.print(
            f"[red]Error:[/red] {path} is a file, not a directory. "
            "Point skillgen at a project root."
        )
        raise typer.Exit(code=1)
    if not resolved.is_dir():
        console.print(f"[red]Error:[/red] {path} is not a directory.")
        raise typer.Exit(code=1)

    try:
        progress = create_progress(quiet=quiet)

        with progress:
            # Phase 1: Detect
            task_detect = progress.add_task("Detecting languages...", total=None)
            project_info = detect_project(resolved, verbose=verbose)
            progress.update(task_detect, completed=True)

            if not project_info.languages:
                console.print(
                    "[red]Error:[/red] No supported language detected. "
                    "Supported: Python, TypeScript, Java, Go, Rust, C++."
                )
                raise typer.Exit(code=1)

            # Phase 2: Analyze
            task_analyze = progress.add_task("Analyzing patterns...", total=None)
            analysis = analyze_project(project_info, verbose=verbose)
            progress.update(task_analyze, completed=True)

            # Phase 3: Generate
            task_generate = progress.add_task("Generating skills...", total=None)
            mode = GenerationMode.LLM if llm else GenerationMode.LOCAL
            generation = generate_skills(
                analysis,
                mode=mode,
                llm_provider=llm_provider,
            )
            progress.update(task_generate, completed=True)

            # Phase 4: Write
            task_write = progress.add_task("Writing files...", total=None)
            written_files = write_skills(
                generation,
                target_dir=resolved,
                output_format=format,
                dry_run=dry_run,
            )
            progress.update(task_write, completed=True)

        # Phase 5: Render
        if dry_run:
            render_dry_run(generation, quiet=quiet)
        if diff:
            render_diff(analysis, generation, format=format)
        if not quiet:
            render_summary(written_files, dry_run=dry_run)

    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Internal error:[/red] {exc}")
        if verbose:
            console.print_exception()
        raise typer.Exit(code=2)
```

---

### 2.2 `detector.py` -- Language and Framework Detection

**Responsibility:** Walks the project directory tree, counts files by extension, reads package manifests and config files, and produces a `ProjectInfo` describing the languages, frameworks, and file inventory of the project.

**Key design decisions:**
- Uses `pathlib` + `os.scandir` for fast traversal (not `os.walk` for performance).
- Respects `.gitignore` via `pathspec` library (lightweight `.gitignore` parser).
- Hardcoded skip list: `.git/`, `node_modules/`, `vendor/`, `__pycache__/`, `build/`, `dist/`, `target/`, `.tox/`, `.venv/`, `venv/`, `.mypy_cache/`.
- Language detection is based on a weighted scoring system: file extensions (weight 1.0), manifest files (weight 5.0), config files (weight 3.0), framework markers (weight 4.0).
- Languages comprising >= 10% of weighted score are included.
- File scanning is parallelized using `concurrent.futures.ThreadPoolExecutor` for I/O-bound manifest reads.

```python
# detector.py -- Key types and constants

from __future__ import annotations
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from skillgen.models import ProjectInfo, LanguageInfo, FrameworkInfo

# Directories to always skip (case-sensitive).
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "vendor", "__pycache__", "build", "dist",
    "target", ".tox", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", "coverage", ".eggs", "egg-info",
})

# Extension -> language mapping.
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",       # Ambiguous: could be C or C++. Resolved later.
    ".hpp": "cpp",
}

# Manifest file -> language mapping (high signal).
MANIFEST_MAP: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "typescript",   # Could be JS; refined by tsconfig presence.
    "tsconfig.json": "typescript",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "CMakeLists.txt": "cpp",
    "Makefile": None,  # Ambiguous; skip.
}

# Framework detection: (file_or_pattern, framework_name, language).
FRAMEWORK_MARKERS: list[tuple[str, str, str]] = [
    # Python
    ("manage.py", "django", "python"),
    ("django", "django", "python"),               # in requirements
    ("flask", "flask", "python"),
    ("fastapi", "fastapi", "python"),
    ("starlette", "starlette", "python"),
    # TypeScript/JavaScript
    ("next.config.js", "nextjs", "typescript"),
    ("next.config.mjs", "nextjs", "typescript"),
    ("next.config.ts", "nextjs", "typescript"),
    ("nuxt.config.ts", "nuxt", "typescript"),
    ("angular.json", "angular", "typescript"),
    ("svelte.config.js", "svelte", "typescript"),
    ("remix.config.js", "remix", "typescript"),
    ("astro.config.mjs", "astro", "typescript"),
    # Java
    ("spring", "spring", "java"),                 # in pom.xml or build.gradle
    ("quarkus", "quarkus", "java"),
    # Go
    ("gin", "gin", "go"),                         # in go.mod
    ("echo", "echo", "go"),
    ("fiber", "fiber", "go"),
    # Rust
    ("actix", "actix", "rust"),                   # in Cargo.toml
    ("axum", "axum", "rust"),
    ("rocket", "rocket", "rust"),
    ("tokio", "tokio", "rust"),
]


def detect_project(root: Path, verbose: bool = False) -> ProjectInfo:
    """
    Scan the project directory and return a ProjectInfo.

    Steps:
    1. Walk directory tree, skipping SKIP_DIRS and respecting .gitignore.
    2. Count files per extension.
    3. Read manifest files to confirm languages.
    4. Search manifests for framework markers.
    5. Build ProjectInfo with languages >= 10% threshold.
    """
    ...


def _load_gitignore(root: Path) -> Optional["pathspec.PathSpec"]:
    """Load .gitignore patterns from the root. Returns None if absent."""
    ...


def _scan_directory(root: Path, gitignore) -> tuple[dict[str, int], list[Path]]:
    """
    Recursively scan directory. Returns:
    - ext_counts: {"python": 142, "typescript": 87, ...}
    - manifest_paths: list of found manifest files
    """
    ...


def _detect_frameworks(manifest_paths: list[Path]) -> list[FrameworkInfo]:
    """Read manifest contents and match against FRAMEWORK_MARKERS."""
    ...
```

---

### 2.3 `analyzer.py` -- AST + Pattern Extraction Engine

**Responsibility:** Given a `ProjectInfo`, selects a representative sample of source files, parses them using tree-sitter (with regex fallback), and extracts patterns across all 8 categories. Produces an `AnalysisResult`.

**Key design decisions:**
- **Sampling strategy:** For each detected language, sample `min(30, ceil(0.2 * file_count))` files. Files are selected from diverse directories (at most 3 files per directory) to ensure broad coverage.
- **AST parsing:** Uses `tree-sitter` Python bindings with pre-compiled language grammars via `tree-sitter-languages` package. Falls back to regex if tree-sitter is unavailable or fails for a given file.
- **Pattern extractors:** Each category has a dedicated extractor class implementing a common `PatternExtractor` protocol. Extractors are language-aware and pluggable.
- **Conflict detection:** When a pattern has multiple variants (e.g., 80% snake_case, 20% camelCase), both are reported with their prevalence.
- **Parallelism:** File parsing is parallelized via `concurrent.futures.ProcessPoolExecutor` to leverage multiple CPU cores.

```python
# analyzer.py -- Architecture sketch

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from skillgen.models import (
    AnalysisResult,
    CodePattern,
    PatternCategory,
    ProjectInfo,
)


class PatternExtractor(Protocol):
    """Protocol for all pattern extractors."""

    category: PatternCategory

    def extract(
        self, file_path: Path, source: str, tree: "Tree | None", language: str
    ) -> list[CodePattern]:
        """Extract patterns from a single file. tree is the tree-sitter AST or None."""
        ...


class NamingConventionExtractor:
    """
    Extracts naming patterns: function casing, class casing, variable casing,
    file naming, constant casing.

    AST approach:
    - Query function_definition, class_definition, variable_declaration nodes.
    - Classify identifiers: snake_case, camelCase, PascalCase, UPPER_SNAKE.

    Regex fallback:
    - Python: r'def\s+(\w+)', r'class\s+(\w+)'
    - TypeScript: r'function\s+(\w+)', r'class\s+(\w+)', r'const\s+(\w+)'
    - Go: r'func\s+(\w+)', r'type\s+(\w+)\s+struct'
    """
    category = PatternCategory.NAMING_CONVENTIONS

    def extract(self, file_path, source, tree, language):
        ...


class ErrorHandlingExtractor:
    """
    Extracts error handling patterns.

    AST approach:
    - Python: try/except blocks, raise statements, custom exception classes.
    - Go: if err != nil blocks, fmt.Errorf patterns, error wrapping.
    - Rust: Result<T, E> usage, ? operator, .unwrap() calls, custom error enums.
    - TypeScript: try/catch blocks, custom error classes, Error subclassing.

    Regex fallback:
    - Python: r'except\s+(\w+)', r'raise\s+(\w+)', r'class\s+(\w+)\(.*Exception'
    - Go: r'if\s+err\s*!=\s*nil', r'fmt\.Errorf\(', r'errors\.(New|Wrap|Is|As)'
    """
    category = PatternCategory.ERROR_HANDLING

    def extract(self, file_path, source, tree, language):
        ...


class TestingPatternExtractor:
    """
    Extracts testing patterns.

    Detects:
    - Test framework (pytest, unittest, jest, mocha, go test, cargo test)
    - Test file naming convention (test_*.py, *.test.ts, *_test.go)
    - Fixture/setup patterns
    - Mocking approach
    - Table-driven test patterns (Go, Rust)
    - Assertion library usage
    """
    category = PatternCategory.TESTING

    def extract(self, file_path, source, tree, language):
        ...


class ImportStyleExtractor:
    """
    Extracts import/module style.

    Detects:
    - Absolute vs. relative imports
    - Import grouping (stdlib / third-party / local)
    - Barrel files / re-exports (index.ts)
    - Import alias conventions
    """
    category = PatternCategory.IMPORTS_AND_DEPENDENCIES

    def extract(self, file_path, source, tree, language):
        ...


class DocumentationStyleExtractor:
    """
    Extracts documentation patterns.

    Detects:
    - Docstring format: Google, NumPy, Sphinx (Python), JSDoc (TS/JS), Javadoc
    - Comment density and style
    - Module-level docstrings
    - README presence and structure
    """
    category = PatternCategory.DOCUMENTATION

    def extract(self, file_path, source, tree, language):
        ...


class ArchitecturePatternExtractor:
    """
    Extracts architecture patterns from directory structure and imports.

    Detects:
    - Layered architecture (controllers/services/repositories)
    - Hexagonal architecture (adapters/ports/domain)
    - Module boundaries
    - Entry point locations (cmd/, main.py, index.ts)
    """
    category = PatternCategory.ARCHITECTURE

    def extract(self, file_path, source, tree, language):
        ...


class CodeStyleExtractor:
    """
    Extracts code style patterns.

    Detects:
    - Max line length (from .editorconfig, formatter config, or measured)
    - Quote style (single vs. double)
    - Trailing commas
    - Semicolons (TS/JS)
    - Formatter in use (black, prettier, gofmt, rustfmt)
    - Linter in use (ruff, eslint, golangci-lint, clippy)
    """
    category = PatternCategory.CODE_STYLE

    def extract(self, file_path, source, tree, language):
        ...


class LoggingObservabilityExtractor:
    """
    Extracts logging and observability patterns.

    Detects:
    - Logger library (logging, structlog, logrus, zerolog, tracing, log4j, winston)
    - Log level usage distribution
    - Structured logging fields
    - Tracing/span patterns
    """
    category = PatternCategory.LOGGING_AND_OBSERVABILITY

    def extract(self, file_path, source, tree, language):
        ...


# The 8th category, API patterns, is detected only when relevant indicators
# are present (HTTP handler files, route definitions, OpenAPI specs, etc.).
class APIPatternExtractor:
    """
    Extracts API patterns (only if the project exposes HTTP/gRPC APIs).

    Detects:
    - Endpoint naming (REST conventions, versioning)
    - Request/response patterns (DTOs, serializers)
    - Validation approach
    - Authentication/middleware patterns
    """
    category = PatternCategory.API_PATTERNS

    def extract(self, file_path, source, tree, language):
        ...


# --- Orchestration ---

ALL_EXTRACTORS: list[PatternExtractor] = [
    NamingConventionExtractor(),
    ErrorHandlingExtractor(),
    TestingPatternExtractor(),
    ImportStyleExtractor(),
    DocumentationStyleExtractor(),
    ArchitecturePatternExtractor(),
    CodeStyleExtractor(),
    LoggingObservabilityExtractor(),
    APIPatternExtractor(),
]


def analyze_project(project_info: ProjectInfo, verbose: bool = False) -> AnalysisResult:
    """
    Main analysis entry point.

    Steps:
    1. For each detected language, select a representative file sample.
    2. For each file, attempt tree-sitter parse; fall back to regex.
    3. Run all extractors against each file.
    4. Aggregate patterns, compute confidence, detect conflicts.
    5. Return AnalysisResult.
    """
    ...


def _select_sample(
    files: list[Path], max_files: int = 30, max_per_dir: int = 3
) -> list[Path]:
    """
    Select a diverse sample of files.

    Algorithm:
    1. Group files by parent directory.
    2. From each directory, take up to max_per_dir files (preferring larger files
       which tend to contain more patterns).
    3. If total < max_files, take additional files from the largest directories.
    4. Cap at max_files.
    """
    ...


def _parse_file(file_path: Path, language: str) -> tuple[str, "Tree | None"]:
    """
    Read and parse a single file.

    Returns (source_text, tree_sitter_tree_or_None).
    Handles: binary files (skip), encoding errors (skip), tree-sitter failures (None).
    """
    ...
```

---

### 2.4 `generator.py` -- Skill Content Generation

**Responsibility:** Takes an `AnalysisResult` and produces a `GenerationResult` containing fully-rendered skill file content. Supports two modes: LOCAL (rule-based templates) and LLM (provider-agnostic API calls to Anthropic or OpenAI).

**Key design decisions:**
- **LOCAL mode** (default, v1.0): Uses string templates with pattern data interpolation. No network access required. Deterministic output.
- **LLM mode** (`--llm` flag): Sends structured analysis data and detailed prompts to an LLM API. Provider is selected via `--llm-provider` flag or auto-detected from environment variables (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).
- **Skill filtering:** A skill is only generated if its category has >= 3 extracted patterns. Below that threshold, the skill is skipped with a verbose log message.
- **Content length target:** Each skill file targets 20-150 lines. The generator enforces this by truncating or consolidating patterns if needed.

```python
# generator.py -- Architecture sketch

from __future__ import annotations

import enum
import time
from typing import Optional

from skillgen.models import (
    AnalysisResult,
    CodePattern,
    GenerationResult,
    PatternCategory,
    SkillDefinition,
)


class GenerationMode(enum.Enum):
    LOCAL = "local"
    LLM = "llm"


class SkillGenerator(ABC):
    """Abstract base for skill generators."""

    @abstractmethod
    def generate(self, analysis: AnalysisResult) -> GenerationResult:
        ...


class LocalGenerator(SkillGenerator):
    """
    Rule-based generator using string templates.
    No network access. Deterministic output.
    """

    MIN_PATTERNS_PER_SKILL = 3
    VERSION = "1.0.0"

    def generate(self, analysis: AnalysisResult) -> GenerationResult:
        start = time.monotonic()
        skills: list[SkillDefinition] = []

        for category in PatternCategory:
            patterns = analysis.patterns_by_category(category)
            if len(patterns) < self.MIN_PATTERNS_PER_SKILL:
                continue  # Skip: insufficient evidence.

            content = self._render_skill(category, patterns, analysis.project_info)
            skill = SkillDefinition(
                name=category.skill_name,
                description=category.description,
                category=category,
                content=content,
                languages=analysis.project_info.language_names,
            )
            skills.append(skill)

        elapsed = time.monotonic() - start
        return GenerationResult(
            skills=skills,
            stats={"categories_attempted": len(PatternCategory),
                   "skills_generated": len(skills)},
            timing_seconds=elapsed,
        )

    def _render_skill(
        self,
        category: PatternCategory,
        patterns: list[CodePattern],
        project_info: "ProjectInfo",
    ) -> str:
        """Render a single skill file's Markdown content from patterns."""
        ...


class LLMGenerator(SkillGenerator):
    """
    LLM-enhanced generator. Sends analysis data to an LLM API.
    Falls back to LocalGenerator on failure.
    """

    def __init__(self, provider: str | None = None):
        self.provider = provider or self._detect_provider()
        self._client = self._init_client()
        self._fallback = LocalGenerator()

    def _detect_provider(self) -> str:
        """Auto-detect provider from environment variables."""
        import os
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        raise EnvironmentError(
            "No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
            "or use --llm-provider to specify a provider."
        )

    def _init_client(self):
        """Initialize the appropriate SDK client."""
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
            # Fall back to local generation on any LLM failure.
            import warnings
            warnings.warn(
                f"LLM generation failed ({exc}). Falling back to local generation."
            )
            return self._fallback.generate(analysis)

    def _generate_with_llm(self, analysis: AnalysisResult) -> GenerationResult:
        """Generate skills using LLM API calls."""
        ...

    def _call_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        """Call Claude via the Anthropic SDK."""
        response = self._client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        """Call GPT-4 via the OpenAI SDK."""
        response = self._client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content


def generate_skills(
    analysis: AnalysisResult,
    mode: GenerationMode = GenerationMode.LOCAL,
    llm_provider: str | None = None,
) -> GenerationResult:
    """Factory function: create the appropriate generator and run it."""
    if mode == GenerationMode.LLM:
        generator = LLMGenerator(provider=llm_provider)
    else:
        generator = LocalGenerator()
    return generator.generate(analysis)
```

---

### 2.5 `writer.py` -- File Output

**Responsibility:** Takes a `GenerationResult` and writes skill files to disk in the requested format(s). Handles directory creation, atomic writes, orphan cleanup, and AGENTS.md append/replace logic.

**Key design decisions:**
- **Atomic writes:** Each file is written to a temporary file in the same directory, then renamed via `os.replace()`. This prevents corruption if the process is killed mid-write.
- **Orphan cleanup:** On each run, the writer reads the existing `.claude/skills/` and `.cursor/rules/` directories, identifies files with the `<!-- Generated by skillgen -->` header that are not in the current generation set, and deletes them.
- **AGENTS.md delimiter:** Uses `<!-- skillgen:start -->` / `<!-- skillgen:end -->` markers. Content between these markers is replaced in full. Content outside them is untouched. If no markers exist, the block is appended at the end.
- **Manual edit protection:** If a skill file exists but does NOT contain the `<!-- Generated by skillgen -->` header, it is assumed to be hand-edited and is never overwritten. A warning is printed.

```python
# writer.py -- Architecture sketch

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from skillgen.models import (
    GenerationResult,
    OutputFormat,
    SkillDefinition,
    WrittenFile,
)

SKILLGEN_HEADER = "<!-- Generated by skillgen v{version} on {date}. Do not edit manually. -->"
AGENTS_MD_START = "<!-- skillgen:start -->"
AGENTS_MD_END = "<!-- skillgen:end -->"


def write_skills(
    generation: GenerationResult,
    target_dir: Path,
    output_format: OutputFormat,
    dry_run: bool = False,
) -> list[WrittenFile]:
    """
    Write generated skills to disk.

    Returns list of WrittenFile records (even in dry-run mode, for reporting).
    """
    written: list[WrittenFile] = []

    if output_format in (OutputFormat.CLAUDE, OutputFormat.ALL):
        written.extend(_write_claude_skills(generation, target_dir, dry_run))

    if output_format in (OutputFormat.CURSOR, OutputFormat.ALL):
        written.extend(_write_cursor_skills(generation, target_dir, dry_run))

    if output_format == OutputFormat.ALL:
        written.extend(_write_agents_md(generation, target_dir, dry_run))

    return written


def _write_claude_skills(
    generation: GenerationResult, target_dir: Path, dry_run: bool
) -> list[WrittenFile]:
    """Write .claude/skills/<name>.md files."""
    skills_dir = target_dir / ".claude" / "skills"
    if not dry_run:
        skills_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_orphans(skills_dir, generation, suffix=".md")

    written = []
    for skill in generation.skills:
        file_path = skills_dir / f"{skill.name}.md"
        content = _format_claude_skill(skill)
        if not dry_run:
            _atomic_write(file_path, content)
        written.append(WrittenFile(
            path=file_path,
            format="claude",
            line_count=content.count("\n") + 1,
            dry_run=dry_run,
        ))
    return written


def _write_cursor_skills(
    generation: GenerationResult, target_dir: Path, dry_run: bool
) -> list[WrittenFile]:
    """Write .cursor/rules/<name>.mdc files."""
    rules_dir = target_dir / ".cursor" / "rules"
    if not dry_run:
        rules_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_orphans(rules_dir, generation, suffix=".mdc")

    written = []
    for skill in generation.skills:
        file_path = rules_dir / f"{skill.name}.mdc"
        content = _format_cursor_skill(skill)
        if not dry_run:
            _atomic_write(file_path, content)
        written.append(WrittenFile(
            path=file_path,
            format="cursor",
            line_count=content.count("\n") + 1,
            dry_run=dry_run,
        ))
    return written


def _write_agents_md(
    generation: GenerationResult, target_dir: Path, dry_run: bool
) -> list[WrittenFile]:
    """Write or update AGENTS.md at the repo root."""
    agents_path = target_dir / "AGENTS.md"
    new_section = _format_agents_md_section(generation)

    if agents_path.exists():
        existing = agents_path.read_text(encoding="utf-8")
        content = _replace_delimited_section(existing, new_section)
    else:
        content = new_section

    if not dry_run:
        _atomic_write(agents_path, content)

    return [WrittenFile(
        path=agents_path,
        format="agents.md",
        line_count=content.count("\n") + 1,
        dry_run=dry_run,
    )]


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a temp file, then atomically rename to target path."""
    dir_path = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _cleanup_orphans(
    directory: Path, generation: GenerationResult, suffix: str
) -> list[Path]:
    """Remove generated files from previous runs that are no longer applicable."""
    ...


def _replace_delimited_section(existing: str, new_section: str) -> str:
    """
    Replace content between <!-- skillgen:start --> and <!-- skillgen:end -->
    markers. If markers don't exist, append new_section at the end.
    """
    ...
```

---

### 2.6 `renderer.py` -- Rich Terminal UI

**Responsibility:** Provides all terminal output: spinners during pipeline phases, the final summary table, diff mode output, dry-run preview, and verbose logging. Uses the `rich` library exclusively for all formatting.

**Key design decisions:**
- **TTY detection:** Uses `rich.console.Console(force_terminal=False)` which auto-detects TTY. When piped, all ANSI codes are stripped.
- **Quiet mode:** Suppresses everything except errors. Implemented by using a `Console` with `quiet=True` or by guarding all output calls.
- **Verbose mode:** Uses `rich.logging.RichHandler` to show structured debug messages for each pipeline step.

```python
# renderer.py -- Architecture sketch

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from skillgen.models import (
    AnalysisResult,
    GenerationResult,
    OutputFormat,
    WrittenFile,
)

console = Console()


def create_progress(quiet: bool = False) -> Progress:
    """Create a Rich progress bar with spinners for each phase."""
    if quiet:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=Console(quiet=True),
        )
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )


def render_summary(written_files: list[WrittenFile], dry_run: bool = False) -> None:
    """
    Render the final summary table.

    Example:
    ┌──────────────────────────────────────────────┬─────────┬───────┐
    │ File                                         │ Format  │ Lines │
    ├──────────────────────────────────────────────┼─────────┼───────┤
    │ .claude/skills/code-style.md                 │ Claude  │    45 │
    │ .claude/skills/testing.md                    │ Claude  │    62 │
    │ .cursor/rules/code-style.mdc                 │ Cursor  │    48 │
    │ AGENTS.md                                    │ AGENTS  │   210 │
    └──────────────────────────────────────────────┴─────────┴───────┘
    """
    table = Table(
        title="Generated Skill Files" + (" (dry run)" if dry_run else ""),
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("File", style="cyan", min_width=40)
    table.add_column("Format", style="green", justify="center")
    table.add_column("Lines", style="yellow", justify="right")

    for wf in sorted(written_files, key=lambda f: str(f.path)):
        table.add_row(str(wf.path), wf.format.title(), str(wf.line_count))

    console.print()
    console.print(table)
    console.print(
        f"\n[bold green]Done![/bold green] "
        f"{len(written_files)} file(s) {'would be ' if dry_run else ''}generated."
    )


def render_diff(
    analysis: AnalysisResult,
    generation: GenerationResult,
    format: OutputFormat,
) -> None:
    """
    Render the --diff comparison table.

    Shows what an AI agent learns with skillgen vs. without.
    Green for new guidance, yellow for updated guidance.
    """
    console.print()
    console.print(
        Panel("[bold]=== Diff: What the AI Agent Learns ===[/bold]", expand=False)
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="bold", min_width=22)
    table.add_column("Without skillgen", style="dim", min_width=24)
    table.add_column("With skillgen", style="green", min_width=45)

    for skill in generation.skills:
        without = _detect_existing_guidance(skill.category, analysis)
        with_sg = _summarize_skill(skill)
        style = "yellow" if without != "(no guidance)" else "green"
        table.add_row(
            skill.category.display_name,
            without,
            Text(with_sg, style=style),
        )

    console.print(table)


def render_dry_run(generation: GenerationResult, quiet: bool = False) -> None:
    """Render dry-run output: file contents to stdout."""
    for skill in generation.skills:
        if not quiet:
            console.print(
                f"\n--- {skill.name} (dry run, not written) ---",
                style="bold blue",
            )
        console.print(skill.content)
        if not quiet:
            console.print()


def _detect_existing_guidance(category, analysis) -> str:
    """Check if existing skill files provide guidance for this category."""
    ...


def _summarize_skill(skill) -> str:
    """One-line summary of a skill's key patterns."""
    ...
```

---

### 2.7 `models.py` -- Data Structures

**Responsibility:** Defines all shared data structures used across modules. All structures are Python dataclasses for clarity, type safety, and IDE support.

```python
# models.py

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# --- Enums ---

class Language(enum.Enum):
    """Supported programming languages."""
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    C = "c"
    CPP = "cpp"

    @property
    def display_name(self) -> str:
        names = {
            "python": "Python",
            "typescript": "TypeScript",
            "javascript": "JavaScript",
            "java": "Java",
            "go": "Go",
            "rust": "Rust",
            "c": "C",
            "cpp": "C++",
        }
        return names[self.value]

    @property
    def extensions(self) -> list[str]:
        ext_map = {
            "python": [".py", ".pyi"],
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx"],
            "java": [".java"],
            "go": [".go"],
            "rust": [".rs"],
            "c": [".c", ".h"],
            "cpp": [".cpp", ".cc", ".cxx", ".hpp"],
        }
        return ext_map[self.value]


class PatternCategory(enum.Enum):
    """The 8 pattern categories extracted by the analyzer."""
    NAMING_CONVENTIONS = "naming-conventions"
    ERROR_HANDLING = "error-handling"
    TESTING = "testing"
    ARCHITECTURE = "architecture"
    IMPORTS_AND_DEPENDENCIES = "imports-and-dependencies"
    DOCUMENTATION = "documentation"
    CODE_STYLE = "code-style"
    LOGGING_AND_OBSERVABILITY = "logging-and-observability"
    API_PATTERNS = "api-patterns"

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
        descriptions = {
            "naming-conventions": "Naming conventions for functions, classes, variables, and files.",
            "error-handling": "How to create, wrap, propagate, and log errors.",
            "testing": "Test framework, file organization, fixtures, assertion style.",
            "architecture": "Directory layout, module boundaries, dependency flow.",
            "imports-and-dependencies": "Import ordering, grouping, approved packages.",
            "documentation": "Docstring format, comment style, documentation conventions.",
            "code-style": "Formatting, line length, quote style, linter/formatter usage.",
            "logging-and-observability": "Logger setup, structured fields, log level usage.",
            "api-patterns": "Request/response patterns, endpoint naming, validation.",
        }
        return descriptions[self.value]


class OutputFormat(str, enum.Enum):
    """Target output format."""
    CLAUDE = "claude"
    CURSOR = "cursor"
    ALL = "all"


class Confidence(enum.Enum):
    """Confidence level for an extracted pattern."""
    LOW = "low"          # < 50% prevalence or inferred indirectly.
    MEDIUM = "medium"    # 50-80% prevalence, direct evidence from code.
    HIGH = "high"        # > 80% prevalence, strong direct evidence.


# --- Core Data Structures ---

@dataclass
class LanguageInfo:
    """Information about a detected language in the project."""
    language: Language
    file_count: int
    file_paths: list[Path] = field(default_factory=list, repr=False)
    percentage: float = 0.0  # Percentage of total source files.


@dataclass
class FrameworkInfo:
    """Information about a detected framework."""
    name: str                   # e.g., "django", "nextjs", "spring"
    language: Language
    evidence: str               # What triggered the detection (e.g., "manage.py found")
    version: str | None = None  # Version if detectable from manifest.


@dataclass
class ProjectInfo:
    """
    Complete description of a detected project.
    Produced by detector.py, consumed by analyzer.py and generator.py.
    """
    root_path: Path
    languages: list[LanguageInfo]
    frameworks: list[FrameworkInfo]
    total_files: int
    source_files: int
    config_files: list[Path] = field(default_factory=list)
    manifest_files: list[Path] = field(default_factory=list)

    @property
    def language_names(self) -> list[str]:
        """Convenience: list of language display names."""
        return [li.language.display_name for li in self.languages]

    @property
    def primary_language(self) -> LanguageInfo:
        """The language with the most files."""
        return max(self.languages, key=lambda li: li.file_count)


@dataclass
class CodePattern:
    """
    A single extracted code pattern.
    Produced by analyzer.py, consumed by generator.py.
    """
    category: PatternCategory
    name: str                   # e.g., "function_naming", "error_wrapping"
    description: str            # Human-readable: "Functions use snake_case"
    evidence: list[str]         # Concrete code snippets from the codebase.
    confidence: Confidence
    prevalence: float = 1.0     # 0.0 to 1.0: what fraction of observed instances follow this pattern.
    language: Language | None = None
    file_path: Path | None = None  # Representative file where pattern was found.
    conflict: str | None = None    # If set, describes the conflicting pattern.
                                   # e.g., "20% of functions use camelCase"

    @property
    def is_conflicted(self) -> bool:
        return self.conflict is not None


@dataclass
class SkillDefinition:
    """
    A generated skill file's content and metadata.
    Produced by generator.py, consumed by writer.py.
    """
    name: str                   # Filename stem: "code-style", "testing", etc.
    description: str            # One-sentence summary.
    category: PatternCategory
    content: str                # The full Markdown content of the skill file body.
    languages: list[str]        # Languages this skill applies to.
    glob_patterns: list[str] = field(default_factory=list)  # For Cursor's globs field.
    always_apply: bool = False  # For Cursor's alwaysApply field.


@dataclass
class AnalysisResult:
    """
    Complete analysis result.
    Produced by analyzer.py, consumed by generator.py.
    """
    project_info: ProjectInfo
    patterns: list[CodePattern]
    files_analyzed: int
    files_skipped: int = 0
    analysis_duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def patterns_by_category(self, category: PatternCategory) -> list[CodePattern]:
        """Return all patterns in a given category."""
        return [p for p in self.patterns if p.category == category]

    def patterns_by_language(self, language: Language) -> list[CodePattern]:
        """Return all patterns for a given language."""
        return [p for p in self.patterns if p.language == language]

    @property
    def categories_with_patterns(self) -> list[PatternCategory]:
        """Return categories that have at least one pattern."""
        return list({p.category for p in self.patterns})


@dataclass
class GenerationResult:
    """
    Result of skill generation.
    Produced by generator.py, consumed by writer.py and renderer.py.
    """
    skills: list[SkillDefinition]
    stats: dict[str, int]           # e.g., {"categories_attempted": 8, "skills_generated": 6}
    timing_seconds: float

    @property
    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]


@dataclass
class WrittenFile:
    """Record of a file written (or that would be written in dry-run mode)."""
    path: Path
    format: str                 # "claude", "cursor", or "agents.md"
    line_count: int
    dry_run: bool = False
```

---

## 3. Data Flow

The pipeline is strictly linear, with no feedback loops. Each stage consumes the output of the previous stage and produces input for the next.

```
                        DATA FLOW DIAGRAM
  ═══════════════════════════════════════════════════════

  INPUT                 PROCESSING                 OUTPUT
  ─────                 ──────────                 ──────

  User provides    ┌─────────────────┐
  a filesystem  -->│   cli.py        │
  path (or ".")    │   validates     │
                   │   path exists   │
                   └────────┬────────┘
                            │ Path
                            v
                   ┌─────────────────┐
                   │  detector.py    │
                   │                 │
                   │  1. os.scandir  │
                   │     recursive   │
                   │     walk        │
                   │                 │
                   │  2. Count exts  │
                   │     per lang    │
                   │                 │
                   │  3. Read        │
                   │     manifests   │
                   │                 │
                   │  4. Match       │
                   │     framework   │
                   │     markers     │
                   └────────┬────────┘
                            │ ProjectInfo
                            │   .languages = [LanguageInfo, ...]
                            │   .frameworks = [FrameworkInfo, ...]
                            │   .total_files = int
                            v
                   ┌─────────────────┐
                   │  analyzer.py    │
                   │                 │
                   │  1. Sample      │
                   │     files       │
                   │     (diverse    │
                   │     dirs)       │
                   │                 │
                   │  2. Parse each: │
                   │     tree-sitter │
                   │     or regex    │
                   │                 │
                   │  3. Run 8+      │
                   │     extractors  │
                   │                 │
                   │  4. Aggregate   │
                   │     & score     │
                   │     patterns    │
                   └────────┬────────┘
                            │ AnalysisResult
                            │   .patterns = [CodePattern, ...]
                            │   .files_analyzed = int
                            │   .project_info = ProjectInfo
                            v
                   ┌─────────────────┐
                   │  generator.py   │
                   │                 │
                   │  LOCAL mode:    │
                   │    template     │
                   │    rendering    │
                   │                 │
                   │  LLM mode:     │
                   │    API call     │
                   │    w/ prompts   │
                   │                 │
                   │  Filter: skip   │
                   │  if < 3 pats   │
                   └────────┬────────┘
                            │ GenerationResult
                            │   .skills = [SkillDefinition, ...]
                            │   .stats = {...}
                            │   .timing_seconds = float
                            v
                   ┌─────────────────┐
                   │  writer.py      │
                   │                 │
                   │  For each skill │
                   │  & each format: │
                   │                 │
                   │  1. Format      │
                   │     content     │
                   │                 │
                   │  2. Atomic      │       ┌──> .claude/skills/code-style.md
                   │     write       │───────┼──> .claude/skills/testing.md
                   │                 │       ├──> .cursor/rules/code-style.mdc
                   │  3. Clean up    │       ├──> .cursor/rules/testing.mdc
                   │     orphans     │       └──> AGENTS.md
                   └────────┬────────┘
                            │ list[WrittenFile]
                            v
                   ┌─────────────────┐
                   │  renderer.py    │──────> Terminal output:
                   │                 │         - Summary table
                   │  Rich console   │         - Diff table (--diff)
                   │  output         │         - Dry-run preview (--dry-run)
                   └─────────────────┘
```

### Timing Budget (10,000-file codebase target: < 15 seconds)

| Phase         | Target Time | Strategy                                       |
|---------------|-------------|------------------------------------------------|
| Detection     | < 2s        | Parallel `os.scandir`, skip vendored dirs early |
| Analysis      | < 10s       | Sample 30 files, parse in parallel (ProcessPool) |
| Generation    | < 1s (local) / < 10s (LLM) | Templates are fast; LLM calls are concurrent |
| Writing       | < 1s        | Atomic writes, small number of files            |
| Rendering     | < 0.5s      | Rich is fast for small tables                   |
| **Total**     | **< 14.5s** |                                                 |

---

## 4. Key Data Structures

All data structures are defined in `models.py` (Section 2.7 above). Here is a consolidated reference with full type annotations and docstrings.

### 4.1 ProjectInfo

```python
@dataclass
class ProjectInfo:
    """
    Complete description of a detected project.

    Produced by: detector.py
    Consumed by: analyzer.py, generator.py

    Example:
        ProjectInfo(
            root_path=Path("/home/user/my-project"),
            languages=[
                LanguageInfo(language=Language.PYTHON, file_count=142, percentage=65.0),
                LanguageInfo(language=Language.TYPESCRIPT, file_count=76, percentage=35.0),
            ],
            frameworks=[
                FrameworkInfo(name="django", language=Language.PYTHON, evidence="manage.py found"),
                FrameworkInfo(name="nextjs", language=Language.TYPESCRIPT, evidence="next.config.js found"),
            ],
            total_files=1200,
            source_files=218,
        )
    """
    root_path: Path
    languages: list[LanguageInfo]
    frameworks: list[FrameworkInfo]
    total_files: int
    source_files: int
    config_files: list[Path] = field(default_factory=list)
    manifest_files: list[Path] = field(default_factory=list)
```

### 4.2 CodePattern

```python
@dataclass
class CodePattern:
    """
    A single extracted code pattern with evidence and confidence.

    Produced by: analyzer.py (one per observation)
    Consumed by: generator.py

    Example:
        CodePattern(
            category=PatternCategory.NAMING_CONVENTIONS,
            name="function_naming",
            description="Functions use snake_case",
            evidence=[
                "def get_user_by_id(user_id: int) -> User:  # src/auth/queries.py:42",
                "def validate_email(email: str) -> bool:  # src/utils/validators.py:15",
            ],
            confidence=Confidence.HIGH,
            prevalence=0.94,
            language=Language.PYTHON,
            file_path=Path("src/auth/queries.py"),
            conflict="6% of functions use camelCase (found in tests/legacy/)",
        )
    """
    category: PatternCategory
    name: str
    description: str
    evidence: list[str]
    confidence: Confidence
    prevalence: float = 1.0
    language: Language | None = None
    file_path: Path | None = None
    conflict: str | None = None
```

### 4.3 SkillDefinition

```python
@dataclass
class SkillDefinition:
    """
    A fully rendered skill file ready for writing.

    Produced by: generator.py
    Consumed by: writer.py

    Example:
        SkillDefinition(
            name="code-style",
            description="Code style conventions for this Python/Django project.",
            category=PatternCategory.CODE_STYLE,
            content="# Code Style\\n\\nThis project uses Black...",
            languages=["Python"],
            glob_patterns=["*.py"],
            always_apply=True,
        )
    """
    name: str
    description: str
    category: PatternCategory
    content: str
    languages: list[str]
    glob_patterns: list[str] = field(default_factory=list)
    always_apply: bool = False
```

### 4.4 AnalysisResult

```python
@dataclass
class AnalysisResult:
    """
    Aggregated analysis of an entire project.

    Produced by: analyzer.py
    Consumed by: generator.py, renderer.py

    Example:
        AnalysisResult(
            project_info=project_info,
            patterns=[...],  # 30-80 CodePattern instances
            files_analyzed=30,
            files_skipped=2,
            analysis_duration_seconds=4.7,
            metadata={"tree_sitter_available": True, "fallback_count": 3},
        )
    """
    project_info: ProjectInfo
    patterns: list[CodePattern]
    files_analyzed: int
    files_skipped: int = 0
    analysis_duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 4.5 GenerationResult

```python
@dataclass
class GenerationResult:
    """
    Output of the skill generation phase.

    Produced by: generator.py
    Consumed by: writer.py, renderer.py

    Example:
        GenerationResult(
            skills=[skill_code_style, skill_testing, ...],
            stats={"categories_attempted": 8, "skills_generated": 6},
            timing_seconds=0.8,
        )
    """
    skills: list[SkillDefinition]
    stats: dict[str, int]
    timing_seconds: float
```

---

## 5. External Dependencies

### Runtime Dependencies

| Package | Version Constraint | Justification |
|---|---|---|
| `rich` | `>=13.0,<15.0` | Terminal UI: spinners, tables, panels, colorized output, TTY detection. The requirements doc (NFR-04) identifies this as the only required runtime dependency. |
| `typer` | `>=0.12,<1.0` | CLI framework: argument parsing, `--help` generation, shell completion, type validation. Builds on `click` but provides a cleaner API with type hints. Typer depends on `rich` already. |
| `pathspec` | `>=0.12,<1.0` | `.gitignore` pattern matching. Lightweight (single-file), widely used (used by `black`), no transitive dependencies. Needed to respect `.gitignore` per FR-05 AC-6. |

### Optional Runtime Dependencies

| Package | Version Constraint | Justification |
|---|---|---|
| `tree-sitter` | `>=0.22,<1.0` | AST parsing for accurate pattern extraction. Optional: if not installed, the analyzer falls back to regex-based extraction. |
| `tree-sitter-languages` | `>=1.10,<2.0` | Pre-compiled language grammars for tree-sitter. Bundles grammars for Python, TypeScript, JavaScript, Java, Go, Rust, C, and C++. Avoids requiring users to compile grammars manually. |
| `anthropic` | `>=0.39,<1.0` | Anthropic SDK for Claude API calls. Only needed when `--llm` flag is used with `--llm-provider anthropic` (or auto-detected via `ANTHROPIC_API_KEY`). |
| `openai` | `>=1.50,<2.0` | OpenAI SDK for GPT-4 API calls. Only needed when `--llm` flag is used with `--llm-provider openai` (or auto-detected via `OPENAI_API_KEY`). |

### Development Dependencies

| Package | Version Constraint | Justification |
|---|---|---|
| `pytest` | `>=8.0` | Test runner. |
| `pytest-cov` | `>=5.0` | Coverage measurement (NFR-05: >= 80% line coverage). |
| `pytest-mock` | `>=3.14` | Mocking utilities for unit tests. |
| `syrupy` | `>=4.0` | Snapshot testing for generated skill file content. |
| `ruff` | `>=0.5` | Linter and formatter (replaces black + isort + flake8). |
| `mypy` | `>=1.11` | Static type checking. |

### Dependency Tree

```
skillgen
├── rich >=13.0,<15.0
├── typer >=0.12,<1.0
│   └── (depends on rich, click)
├── pathspec >=0.12,<1.0
├── [optional] tree-sitter >=0.22,<1.0
├── [optional] tree-sitter-languages >=1.10,<2.0
├── [optional] anthropic >=0.39,<1.0
└── [optional] openai >=1.50,<2.0
```

### `pyproject.toml` Dependency Declaration

```toml
[project]
name = "skillgen"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "rich>=13.0,<15.0",
    "typer>=0.12,<1.0",
    "pathspec>=0.12,<1.0",
]

[project.optional-dependencies]
ast = [
    "tree-sitter>=0.22,<1.0",
    "tree-sitter-languages>=1.10,<2.0",
]
llm = [
    "anthropic>=0.39,<1.0",
    "openai>=1.50,<2.0",
]
all = [
    "skillgen[ast,llm]",
]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-mock>=3.14",
    "syrupy>=4.0",
    "ruff>=0.5",
    "mypy>=1.11",
]

[project.scripts]
skillgen = "skillgen.cli:app"
```

---

## 6. LLM Prompt Templates

The LLM mode uses two prompts per skill category: a **system prompt** (shared across all categories) and a **user prompt** (category-specific, includes analysis data).

### 6.1 System Prompt (Shared)

```python
SYSTEM_PROMPT = """\
You are an expert software architect generating AI agent skill files for the \
tool "skillgen". Your job is to produce a single, focused Markdown skill file \
that an AI coding assistant (Claude Code, Cursor, GitHub Copilot) will read to \
understand one specific aspect of a project's conventions.

RULES:
1. Be SPECIFIC to this project. Reference actual file paths, class names, \
function signatures, and patterns observed in the analysis data provided. \
Never produce generic boilerplate.
2. Every claim must be grounded in the "Evidence" data provided. If the \
evidence is insufficient, say "Not enough data to determine" rather than \
guessing.
3. Keep the output between 20 and 150 lines of Markdown. Aim for \
approximately 60-80 lines. Be concise but complete.
4. Start with a one-sentence summary of the key convention (this becomes the \
AI assistant's first impression).
5. Use H2 (##) headings to organize subsections. Do not use H1 (#) -- the \
skill file title is added separately.
6. Include concrete code examples drawn from the evidence. Format them as \
fenced code blocks with the correct language tag.
7. When patterns conflict (e.g., 80% snake_case, 20% camelCase), state both \
and indicate which is the dominant convention.
8. End with a "## Exceptions" section if there are any valid exceptions to \
the conventions (e.g., "Legacy code in `src/legacy/` uses a different style \
and should not be changed to match").
9. Write in the imperative mood, addressed to the AI assistant: "Use \
snake_case for function names" not "The project uses snake_case".
10. Do not include the <!-- Generated by skillgen --> header or any YAML \
front matter. Those are added by the tool. Only output the Markdown body.\
"""
```

### 6.2 User Prompt Template (Per-Category)

```python
USER_PROMPT_TEMPLATE = """\
Generate a **{category_display_name}** skill file for the following project.

## Project Summary
- **Root path:** {root_path}
- **Languages:** {languages}
- **Frameworks:** {frameworks}
- **Total source files:** {source_file_count}

## Detected Patterns for "{category_display_name}"

{patterns_section}

## Instructions

Using ONLY the patterns and evidence above, generate a Markdown skill file \
body for the "{category_display_name}" category. Follow the rules in your \
system prompt.

If a pattern has a conflict noted, mention both the dominant convention and \
the minority convention with their prevalence percentages.

Output ONLY the Markdown body. No preamble, no explanation, no wrapping.\
"""
```

### 6.3 Pattern Section Formatter

The `{patterns_section}` placeholder is populated by formatting each `CodePattern` as follows:

```python
def _format_patterns_for_prompt(patterns: list[CodePattern]) -> str:
    """Format patterns into a structured text block for the LLM prompt."""
    sections = []
    for i, p in enumerate(patterns, 1):
        lines = [
            f"### Pattern {i}: {p.name}",
            f"- **Description:** {p.description}",
            f"- **Confidence:** {p.confidence.value}",
            f"- **Prevalence:** {p.prevalence:.0%}",
        ]
        if p.conflict:
            lines.append(f"- **Conflict:** {p.conflict}")
        if p.file_path:
            lines.append(f"- **Representative file:** `{p.file_path}`")
        lines.append("- **Evidence:**")
        for ev in p.evidence[:5]:  # Cap at 5 examples to fit context window.
            lines.append(f"  ```")
            lines.append(f"  {ev}")
            lines.append(f"  ```")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
```

### 6.4 Full Prompt Example (Rendered)

Below is what a fully rendered prompt would look like for the "Testing" category of a Python/pytest project:

```
[SYSTEM PROMPT as defined in 6.1]

[USER PROMPT]
Generate a **Testing** skill file for the following project.

## Project Summary
- **Root path:** /home/user/my-django-app
- **Languages:** Python (85%), TypeScript (15%)
- **Frameworks:** Django 4.2, Next.js 14
- **Total source files:** 342

## Detected Patterns for "Testing"

### Pattern 1: test_framework
- **Description:** Tests use pytest as the primary test runner
- **Confidence:** high
- **Prevalence:** 100%
- **Representative file:** `tests/conftest.py`
- **Evidence:**
  ```
  # pyproject.toml: [tool.pytest.ini_options]
  ```
  ```
  # tests/conftest.py: import pytest
  ```

### Pattern 2: test_file_naming
- **Description:** Test files follow the pattern test_<module>.py
- **Confidence:** high
- **Prevalence:** 96%
- **Conflict:** 4% of test files use <module>_test.py (found in tests/legacy/)
- **Representative file:** `tests/auth/test_login.py`
- **Evidence:**
  ```
  tests/auth/test_login.py
  tests/auth/test_permissions.py
  tests/api/test_endpoints.py
  ```

### Pattern 3: fixture_usage
- **Description:** Fixtures are defined in conftest.py at each directory level
- **Confidence:** high
- **Prevalence:** 100%
- **Representative file:** `tests/conftest.py`
- **Evidence:**
  ```
  # tests/conftest.py
  @pytest.fixture
  def db_session():
      ...
  ```
  ```
  # tests/auth/conftest.py
  @pytest.fixture
  def authenticated_user(db_session):
      ...
  ```

### Pattern 4: mock_style
- **Description:** Mocking uses unittest.mock.patch as a decorator
- **Confidence:** medium
- **Prevalence:** 78%
- **Conflict:** 22% use patch as a context manager
- **Representative file:** `tests/auth/test_login.py`
- **Evidence:**
  ```
  @patch("src.auth.login.get_user")
  def test_login_success(mock_get_user, authenticated_user):
      ...
  ```

### Pattern 5: assertion_style
- **Description:** Plain assert statements are used (not self.assertEqual)
- **Confidence:** high
- **Prevalence:** 100%
- **Evidence:**
  ```
  assert response.status_code == 200
  assert user.email == "test@example.com"
  assert result == pytest.approx(3.14, rel=1e-2)
  ```

## Instructions

Using ONLY the patterns and evidence above, generate a Markdown skill file
body for the "Testing" category. Follow the rules in your system prompt.

If a pattern has a conflict noted, mention both the dominant convention and
the minority convention with their prevalence percentages.

Output ONLY the Markdown body. No preamble, no explanation, no wrapping.
```

### 6.5 Local Mode Templates

When LLM mode is not used, the `LocalGenerator` uses structured string templates. These produce output that is functional but less polished than LLM-generated content.

```python
LOCAL_SKILL_TEMPLATE = """\
{summary_sentence}

{sections}
"""

LOCAL_SECTION_TEMPLATE = """\
## {heading}

{body}
"""

LOCAL_PATTERN_TEMPLATE = """\
- {description}{conflict_note}
  ```{lang}
  {evidence_snippet}
  ```
"""


def _render_local_skill(
    category: PatternCategory,
    patterns: list[CodePattern],
    project_info: ProjectInfo,
) -> str:
    """
    Render a skill file using local templates (no LLM).

    Strategy:
    1. Group patterns by sub-topic (e.g., within Testing: framework, naming,
       fixtures, mocking, assertions).
    2. For each group, render a section with heading, description, and evidence.
    3. Assemble into the final Markdown body.
    """
    # Build summary sentence from the most confident pattern.
    top_pattern = max(patterns, key=lambda p: (p.confidence.value, p.prevalence))
    summary = (
        f"This project's {category.display_name.lower()} conventions are "
        f"centered around {top_pattern.description.lower()}."
    )

    # Group patterns by name prefix (e.g., "test_framework", "test_file_naming"
    # both start with "test_").
    grouped = _group_patterns(patterns)

    sections = []
    for heading, group_patterns in grouped.items():
        body_parts = []
        for p in group_patterns:
            conflict_note = ""
            if p.conflict:
                conflict_note = f" ({p.conflict})"
            evidence = p.evidence[0] if p.evidence else "No example available."
            lang = _language_tag(p.language)
            body_parts.append(
                LOCAL_PATTERN_TEMPLATE.format(
                    description=p.description,
                    conflict_note=conflict_note,
                    lang=lang,
                    evidence_snippet=evidence,
                )
            )
        sections.append(
            LOCAL_SECTION_TEMPLATE.format(
                heading=heading,
                body="\n".join(body_parts),
            )
        )

    return LOCAL_SKILL_TEMPLATE.format(
        summary_sentence=summary,
        sections="\n".join(sections),
    )
```

---

## 7. File Output Format Specs

### 7.1 Claude Skill Files (`.claude/skills/<skill-name>.md`)

**Location:** `<project-root>/.claude/skills/<skill-name>.md`

**Format:** Markdown with an HTML comment header. No YAML front matter (Claude Code skill files use plain Markdown).

**Template:**

```markdown
<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

# {Skill Display Name}

{skill_content_body}
```

**Concrete example (`.claude/skills/testing.md`):**

```markdown
<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

# Testing Conventions

This project uses **pytest** with fixtures defined in `conftest.py` at each directory level.

## Test File Naming

- Name test files `test_<module>.py` mirroring the source structure.
- Example: `src/auth/login.py` is tested in `tests/auth/test_login.py`.

## Fixture Patterns

- Define shared fixtures in `tests/conftest.py`.
- Define domain-specific fixtures in `tests/<domain>/conftest.py`.
- Fixtures that hit the database are marked `@pytest.mark.db`.

## Assertion Style

- Use plain `assert` statements, not `self.assertEqual`.
- For approximate floats: `assert value == pytest.approx(expected, rel=1e-3)`.

## Mocking

- Use `unittest.mock.patch` as a decorator, not as a context manager.
- Patch at the import site: `@patch("src.auth.login.get_user")`, not `@patch("src.auth.models.get_user")`.

## Running Tests

- `pytest tests/` -- run all tests.
- `pytest tests/auth/` -- run a single domain.
- `pytest -k "test_login"` -- run by name pattern.
```

**File naming convention:** The filename is derived from `PatternCategory.skill_name` (e.g., `code-style`, `error-handling`, `testing`). Always lowercase, hyphen-separated.

---

### 7.2 Cursor Rule Files (`.cursor/rules/<skill-name>.mdc`)

**Location:** `<project-root>/.cursor/rules/<skill-name>.mdc`

**Format:** YAML front matter (delimited by `---`) followed by Markdown body. The `.mdc` extension is Cursor's convention.

**Front matter fields:**

| Field | Type | Description |
|---|---|---|
| `description` | string | One-sentence summary of the rule. |
| `globs` | string or list | File glob patterns this rule applies to. |
| `alwaysApply` | boolean | If `true`, the rule is always active. If `false`, it only activates when matching files are open. |

**`alwaysApply` logic:**
- `true` for: `architecture`, `code-style` (these are always relevant).
- `false` for all other categories (they are language/file-specific).

**`globs` logic:**
- Derived from the detected languages. For a Python project: `"*.py"`.
- For a polyglot project with both Python and TypeScript: `["*.py", "*.ts", "*.tsx"]`.
- For `architecture` (always-apply): `""` (empty string, meaning all files).

**Template:**

```
---
description: {one_sentence_description}
globs: {glob_patterns}
alwaysApply: {true|false}
---

<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

{skill_content_body}
```

**Concrete example (`.cursor/rules/testing.mdc`):**

```
---
description: Testing conventions for this Python/Django project using pytest.
globs: "*.py"
alwaysApply: false
---

<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

# Testing Conventions

This project uses **pytest** with fixtures defined in `conftest.py` at each directory level.

## Test File Naming

- Name test files `test_<module>.py` mirroring the source structure.
- Example: `src/auth/login.py` is tested in `tests/auth/test_login.py`.

## Fixture Patterns

- Define shared fixtures in `tests/conftest.py`.
- Define domain-specific fixtures in `tests/<domain>/conftest.py`.
- Fixtures that hit the database are marked `@pytest.mark.db`.

## Assertion Style

- Use plain `assert` statements, not `self.assertEqual`.
- For approximate floats: `assert value == pytest.approx(expected, rel=1e-3)`.

## Mocking

- Use `unittest.mock.patch` as a decorator, not as a context manager.
- Patch at the import site: `@patch("src.auth.login.get_user")`, not `@patch("src.auth.models.get_user")`.
```

---

### 7.3 AGENTS.md

**Location:** `<project-root>/AGENTS.md`

**Format:** Standard Markdown. H2 headings per skill category. Wrapped in delimiter comments for safe incremental updates.

**Delimiter convention:**
- `<!-- skillgen:start -->` marks the beginning of the generated section.
- `<!-- skillgen:end -->` marks the end.
- Content outside these delimiters is NEVER modified.
- On subsequent runs, only the content between the delimiters is replaced.

**Template:**

```markdown
<!-- skillgen:start -->
<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

# Project Conventions (Auto-Generated)

This section was generated by [skillgen](https://github.com/skillgen/skillgen) to help AI coding assistants understand this project's conventions.

{for each skill:}
## {Skill Display Name}

{skill_content_body}

{end for}
<!-- skillgen:end -->
```

**Concrete example (`AGENTS.md` for a Python/Django project):**

```markdown
<!-- skillgen:start -->
<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

# Project Conventions (Auto-Generated)

This section was generated by [skillgen](https://github.com/skillgen/skillgen) to help AI coding assistants understand this project's conventions.

## Code Style

This project uses **Black** formatter with a line length of 88 and **isort** for import sorting.

- Use `snake_case` for functions and variables.
- Use `PascalCase` for classes.
- Use `UPPER_SNAKE_CASE` for constants.
- Use double quotes for strings.
- Always add trailing commas in multi-line collections.

## Error Handling

Errors are handled using explicit exception classes defined in `src/exceptions.py`.

- Wrap lower-level exceptions: `raise ServiceError("context") from original_error`.
- Never use bare `except:` -- always catch a specific exception type.
- Log errors with `logger.exception()` to capture the traceback.

## Testing

This project uses **pytest** with fixtures defined in `conftest.py` at each directory level.

- Name test files `test_<module>.py` mirroring the source structure.
- Use `unittest.mock.patch` as a decorator.
- Use plain `assert` statements.

## Architecture

This project follows a layered architecture.

- `src/api/` -- Django REST Framework views and serializers.
- `src/services/` -- Business logic. Views call services, never the ORM directly.
- `src/repositories/` -- Data access layer wrapping Django ORM queries.
- `src/models/` -- Django model definitions.
- `tests/` -- Mirrors `src/` structure.

## Imports and Dependencies

- Imports are grouped: stdlib, third-party, local (enforced by isort).
- Never use relative imports.
- Approved external packages are listed in `pyproject.toml` under `[project.dependencies]`.

## Documentation

- All public functions have Google-style docstrings with `Args`, `Returns`, and `Raises` sections.
- Module-level docstrings are required for all files in `src/`.
- Use `# TODO(username):` format for inline TODOs.

<!-- skillgen:end -->
```

---

## 8. Error Handling Strategy

### 8.1 Error Categories and Exit Codes

| Exit Code | Category | When |
|---|---|---|
| 0 | Success | Pipeline completed normally. |
| 1 | User Error | Invalid path, path is a file, no supported language detected, invalid CLI flags. |
| 2 | Internal Error | Unhandled exception, I/O failure during write, corrupted analysis state. |

### 8.2 Error Handling by Module

#### `cli.py`

| Error Condition | Handling | User Message |
|---|---|---|
| Path does not exist | Exit code 1 | `"Error: <path> does not exist."` |
| Path is a file | Exit code 1 | `"Error: <path> is a file, not a directory. Point skillgen at a project root."` |
| Path is not a directory | Exit code 1 | `"Error: <path> is not a directory."` |
| Any unhandled exception | Catch at top level, exit code 2 | `"Internal error: <exception message>"` |
| `--verbose` + exception | Print full traceback via `console.print_exception()` | Full stack trace |
| `--quiet` + error | Still print error messages (quiet suppresses progress, not errors) | Error message only |

#### `detector.py`

| Error Condition | Handling | User Message |
|---|---|---|
| No supported language found | Return empty `ProjectInfo.languages` (cli.py handles the exit) | (handled by cli.py) |
| `.gitignore` parse failure | Log warning, proceed without gitignore filtering | `"Warning: Could not parse .gitignore. Scanning all files."` |
| Permission denied on directory | Skip directory, log warning | `"Warning: Permission denied: <path>. Skipping."` |
| Symlink loop detected | Skip via `os.scandir` (does not follow symlinks by default) | (silent skip) |

#### `analyzer.py`

| Error Condition | Handling | User Message |
|---|---|---|
| tree-sitter not installed | Fall back to regex for all files | `"Note: tree-sitter not installed. Using regex-based analysis (less accurate). Install with: pip install skillgen[ast]"` |
| tree-sitter grammar not available for language | Fall back to regex for that language | (verbose-only warning) |
| tree-sitter parse failure on a file | Fall back to regex for that file, increment `files_skipped` | (verbose-only warning) |
| Binary file encountered | Skip, increment `files_skipped` | (verbose-only warning) |
| Non-UTF-8 file encountered | Skip, increment `files_skipped` | (verbose-only warning) |
| File read permission denied | Skip, increment `files_skipped` | (verbose-only warning) |
| No patterns extracted for any category | Return `AnalysisResult` with empty patterns (generator handles this) | (generator will produce 0 skills, renderer will note this) |

#### `generator.py`

| Error Condition | Handling | User Message |
|---|---|---|
| LLM mode: no API key in environment | Raise `EnvironmentError` (caught by cli.py) | `"Error: No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."` |
| LLM mode: API rate limit | Fall back to LocalGenerator with warning | `"Warning: LLM rate limited. Falling back to local generation."` |
| LLM mode: API timeout (30s) | Fall back to LocalGenerator with warning | `"Warning: LLM request timed out. Falling back to local generation."` |
| LLM mode: API returns error | Fall back to LocalGenerator with warning | `"Warning: LLM generation failed (<error>). Falling back to local generation."` |
| LLM mode: response is malformed/too short | Fall back to LocalGenerator for that skill | (verbose-only warning) |
| No skills generated (all categories < 3 patterns) | Return empty `GenerationResult` | `"Warning: No skill files generated. The codebase did not have enough detectable patterns."` |

#### `writer.py`

| Error Condition | Handling | User Message |
|---|---|---|
| Cannot create output directory | Raise `OSError` (caught by cli.py, exit code 2) | `"Internal error: Could not create directory <path>: <reason>"` |
| Write failure (disk full, permissions) | Clean up temp file, raise `OSError` | `"Internal error: Could not write <path>: <reason>"` |
| Existing file without skillgen header (hand-edited) | Skip writing, do NOT overwrite | `"Skipped: <path> (manually edited, missing skillgen header)"` |
| AGENTS.md exists but cannot be read | Raise `OSError` | `"Internal error: Could not read existing AGENTS.md: <reason>"` |
| Atomic rename fails | Clean up temp file, raise `OSError` | `"Internal error: Could not finalize <path>: <reason>"` |

### 8.3 Graceful Degradation Hierarchy

The system degrades gracefully in a defined order:

```
Optimal path:  tree-sitter AST  -->  LLM generation  -->  full output
                    |                     |
                    v                     v
Fallback 1:    regex analysis   -->  LLM generation  -->  full output
                                          |
                                          v
Fallback 2:    regex analysis   -->  local templates  -->  full output
                                                              |
                                                              v
Fallback 3:    regex analysis   -->  local templates  -->  partial output
               (some files                                 (some skills
                skipped)                                    skipped)
                                                              |
                                                              v
Minimum:       file counting    -->  "No patterns      -->  exit code 1
               only                   detected" error
```

---

## 9. Testing Strategy

### 9.1 Test Directory Structure

```
tests/
├── conftest.py                      # Shared fixtures
├── fixtures/                        # Synthetic codebases for testing
│   ├── python_django/               # Python/Django project
│   │   ├── manage.py
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── auth/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── login.py
│   │   │   │   └── models.py
│   │   │   ├── services/
│   │   │   │   └── user_service.py
│   │   │   └── exceptions.py
│   │   └── tests/
│   │       ├── conftest.py
│   │       └── auth/
│   │           ├── conftest.py
│   │           └── test_login.py
│   ├── typescript_nextjs/           # TypeScript/Next.js project
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── next.config.js
│   │   └── src/
│   │       ├── components/
│   │       ├── pages/
│   │       └── utils/
│   ├── go_api/                      # Go API project
│   │   ├── go.mod
│   │   ├── cmd/
│   │   │   └── server/
│   │   │       └── main.go
│   │   └── internal/
│   │       ├── handlers/
│   │       └── repository/
│   ├── rust_cli/                    # Rust CLI project
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs
│   │       └── lib.rs
│   ├── java_spring/                 # Java/Spring project
│   │   ├── pom.xml
│   │   └── src/
│   │       └── main/
│   │           └── java/
│   ├── polyglot/                    # Multi-language project
│   │   ├── pyproject.toml
│   │   ├── package.json
│   │   ├── backend/                 # Python
│   │   └── frontend/               # TypeScript
│   ├── empty/                       # Empty directory (edge case)
│   ├── no_language/                 # Only .txt and .md files
│   └── hand_edited/                 # Has pre-existing hand-edited skill files
│       ├── .claude/
│       │   └── skills/
│       │       └── testing.md       # No skillgen header (hand-edited)
│       └── AGENTS.md                # Has content outside delimiters
├── unit/
│   ├── test_detector.py
│   ├── test_analyzer.py
│   ├── test_generator.py
│   ├── test_writer.py
│   ├── test_renderer.py
│   └── test_models.py
├── integration/
│   ├── test_cli.py
│   ├── test_full_pipeline.py
│   └── test_idempotency.py
└── snapshots/                       # Snapshot files for syrupy
    └── ...
```

### 9.2 Unit Test Plan

#### `test_detector.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| DET-01 | `test_detect_python_project` | Run detector on `fixtures/python_django/` | Languages contains Python. Frameworks contains Django. File counts are correct. |
| DET-02 | `test_detect_typescript_project` | Run detector on `fixtures/typescript_nextjs/` | Languages contains TypeScript. Frameworks contains Next.js. |
| DET-03 | `test_detect_go_project` | Run detector on `fixtures/go_api/` | Languages contains Go. `go.mod` detected. |
| DET-04 | `test_detect_rust_project` | Run detector on `fixtures/rust_cli/` | Languages contains Rust. `Cargo.toml` detected. |
| DET-05 | `test_detect_java_project` | Run detector on `fixtures/java_spring/` | Languages contains Java. Frameworks contains Spring. |
| DET-06 | `test_detect_polyglot` | Run detector on `fixtures/polyglot/` | Both Python and TypeScript detected. Each >= 10% threshold. |
| DET-07 | `test_detect_empty_directory` | Run detector on `fixtures/empty/` | `languages` is empty list. `total_files` is 0. |
| DET-08 | `test_detect_no_supported_language` | Run detector on `fixtures/no_language/` | `languages` is empty list. |
| DET-09 | `test_skip_vendored_dirs` | Create temp dir with `node_modules/` containing `.js` files | `node_modules/` files are not counted. |
| DET-10 | `test_gitignore_respected` | Create temp dir with `.gitignore` excluding `generated/` | Files in `generated/` are not counted. |
| DET-11 | `test_framework_detection_from_manifest` | Create temp `pyproject.toml` with `django` dependency | Framework "django" detected with correct evidence string. |
| DET-12 | `test_performance_large_dir` | Create temp dir with 10,000 empty `.py` files | Detection completes in < 2 seconds. |
| DET-13 | `test_symlink_handling` | Create temp dir with symlink loop | No crash. Symlinked files are skipped or handled. |
| DET-14 | `test_percentage_calculation` | 70 `.py` files and 30 `.ts` files | Python: 70%, TypeScript: 30%. |

#### `test_analyzer.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| ANA-01 | `test_analyze_python_naming` | Analyze `fixtures/python_django/` | Patterns include `function_naming` with `snake_case` description and HIGH confidence. |
| ANA-02 | `test_analyze_python_testing` | Analyze `fixtures/python_django/` | Patterns include `test_framework` with `pytest` description. Evidence references actual conftest.py. |
| ANA-03 | `test_analyze_python_error_handling` | Analyze `fixtures/python_django/` | Patterns include error handling patterns with evidence from `exceptions.py`. |
| ANA-04 | `test_analyze_go_error_handling` | Analyze `fixtures/go_api/` | Patterns include `if err != nil` pattern. |
| ANA-05 | `test_analyze_typescript_imports` | Analyze `fixtures/typescript_nextjs/` | Patterns include import style patterns. |
| ANA-06 | `test_sample_selection_diverse` | 100 files across 20 dirs, max_files=30, max_per_dir=3 | Sample contains files from >= 10 different directories. Sample size <= 30. |
| ANA-07 | `test_sample_selection_small_project` | 10 files total | All 10 files are included (below the 30 cap). |
| ANA-08 | `test_regex_fallback_when_no_treesitter` | Mock tree-sitter as unavailable | Analysis still produces patterns. `metadata["tree_sitter_available"]` is `False`. |
| ANA-09 | `test_conflict_detection` | Create files with 80% snake_case, 20% camelCase functions | Pattern has `conflict` field set with prevalence info. |
| ANA-10 | `test_binary_file_skipped` | Include a binary file (`.png`) in the project | `files_skipped >= 1`. No crash. |
| ANA-11 | `test_non_utf8_file_skipped` | Include a file with Latin-1 encoding | `files_skipped >= 1`. No crash. |
| ANA-12 | `test_minimum_categories_populated` | Analyze `fixtures/python_django/` | At least 5 of 8 categories have patterns. |
| ANA-13 | `test_evidence_contains_actual_code` | Analyze any fixture | Every `CodePattern.evidence` list is non-empty and contains strings from the fixture source files. |
| ANA-14 | `test_architecture_detection` | Analyze `fixtures/go_api/` | Detects `cmd/` for entrypoints and `internal/` for libraries. |

#### `test_generator.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| GEN-01 | `test_local_generate_produces_skills` | Generate with LOCAL mode from a full AnalysisResult | `GenerationResult.skills` is non-empty. Each skill has content between 20-150 lines. |
| GEN-02 | `test_local_skip_insufficient_patterns` | Category with 2 patterns | That category is NOT in the generated skills. |
| GEN-03 | `test_local_include_sufficient_patterns` | Category with 5 patterns | That category IS in the generated skills. |
| GEN-04 | `test_local_skill_starts_with_summary` | Generate any skill | First non-empty line of content is a summary sentence (not a heading). |
| GEN-05 | `test_local_skill_references_project` | Generate skills for `fixtures/python_django/` | Content references actual paths like `src/auth/`, `tests/conftest.py`. |
| GEN-06 | `test_local_skill_line_count` | Generate all skills | Every skill has `content.count("\n") + 1` between 20 and 150. |
| GEN-07 | `test_llm_fallback_on_api_error` | Mock LLM to raise exception | Falls back to LocalGenerator. Warning is issued. Result is non-empty. |
| GEN-08 | `test_llm_fallback_on_missing_key` | No API key in environment | Raises `EnvironmentError` (or falls back if called from pipeline). |
| GEN-09 | `test_llm_anthropic_prompt_format` | Mock Anthropic client, capture prompt | System prompt matches `SYSTEM_PROMPT`. User prompt contains project info and patterns. |
| GEN-10 | `test_llm_openai_prompt_format` | Mock OpenAI client, capture prompt | Messages list contains system and user messages with correct content. |
| GEN-11 | `test_generation_timing` | Generate skills | `timing_seconds` is a positive float. |
| GEN-12 | `test_generation_stats` | Generate skills | `stats` contains `categories_attempted` and `skills_generated` keys. |
| GEN-13 | `test_conflict_appears_in_content` | Pattern with `conflict` set | Generated content mentions both the dominant and minority convention. |

#### `test_writer.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| WRT-01 | `test_write_claude_skills` | Write with format=CLAUDE | `.claude/skills/` directory created. Correct `.md` files written. |
| WRT-02 | `test_write_cursor_skills` | Write with format=CURSOR | `.cursor/rules/` directory created. Correct `.mdc` files written. |
| WRT-03 | `test_write_agents_md` | Write with format=ALL | `AGENTS.md` created at root. |
| WRT-04 | `test_claude_file_has_header` | Read written Claude file | First line matches `<!-- Generated by skillgen v... -->`. |
| WRT-05 | `test_cursor_file_has_frontmatter` | Read written Cursor file | File starts with `---`, contains `description`, `globs`, `alwaysApply` keys, ends front matter with `---`. |
| WRT-06 | `test_cursor_frontmatter_valid_yaml` | Parse Cursor file front matter | `yaml.safe_load()` succeeds. Contains expected keys. |
| WRT-07 | `test_agents_md_delimiters` | Read AGENTS.md | Contains `<!-- skillgen:start -->` and `<!-- skillgen:end -->`. |
| WRT-08 | `test_agents_md_append_preserves_existing` | Write to dir with existing AGENTS.md content outside delimiters | Existing content outside delimiters is unchanged. |
| WRT-09 | `test_agents_md_replace_on_rerun` | Write twice to same dir | Content between delimiters is replaced. No duplication. |
| WRT-10 | `test_dry_run_no_files_written` | Write with dry_run=True | No files created on disk. `WrittenFile.dry_run` is `True`. |
| WRT-11 | `test_atomic_write_cleanup_on_failure` | Mock `os.replace` to raise | No `.tmp` files left behind. |
| WRT-12 | `test_orphan_cleanup` | First run generates `testing.md`, second run does not | `testing.md` is deleted. |
| WRT-13 | `test_hand_edited_file_not_overwritten` | Existing file without skillgen header | File is not modified. Warning is logged. |
| WRT-14 | `test_idempotency` | Write twice with identical GenerationResult | Output files are byte-for-byte identical. |
| WRT-15 | `test_directory_creation` | Write to path where `.claude/skills/` does not exist | Directory is created automatically. |

#### `test_renderer.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| REN-01 | `test_summary_table_content` | Render summary with 3 WrittenFile records | Output contains all 3 file paths, formats, and line counts. |
| REN-02 | `test_diff_table_content` | Render diff | Output contains category names and pattern summaries. |
| REN-03 | `test_dry_run_output` | Render dry run | Each skill's content appears in output. Headers present when not quiet. |
| REN-04 | `test_quiet_mode` | Render summary with quiet=True | No output produced (except errors). |
| REN-05 | `test_no_ansi_when_piped` | Render with Console(force_terminal=False) to a StringIO | Output contains no ANSI escape codes. |

#### `test_models.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| MOD-01 | `test_pattern_category_skill_name` | All PatternCategory values | `skill_name` returns a valid filename-safe string. |
| MOD-02 | `test_language_extensions` | All Language values | `extensions` returns a non-empty list. |
| MOD-03 | `test_analysis_result_patterns_by_category` | Create AnalysisResult with patterns | `patterns_by_category()` filters correctly. |
| MOD-04 | `test_project_info_primary_language` | ProjectInfo with 2 languages | `primary_language` returns the one with more files. |
| MOD-05 | `test_code_pattern_is_conflicted` | Pattern with and without conflict | `is_conflicted` returns correct boolean. |

### 9.3 Integration Test Plan

#### `test_cli.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| INT-01 | `test_cli_basic_run` | Run `skillgen fixtures/python_django/` | Exit code 0. Files created in `.claude/skills/`, `.cursor/rules/`, and `AGENTS.md`. |
| INT-02 | `test_cli_format_claude_only` | Run with `--format claude` | Only `.claude/skills/` files created. No `.cursor/rules/` or `AGENTS.md`. |
| INT-03 | `test_cli_format_cursor_only` | Run with `--format cursor` | Only `.cursor/rules/` files created. |
| INT-04 | `test_cli_dry_run` | Run with `--dry-run` | Exit code 0. No files written to disk. Output contains skill content. |
| INT-05 | `test_cli_diff_mode` | Run with `--diff` | Exit code 0. Output contains diff table with "Without skillgen" and "With skillgen" columns. |
| INT-06 | `test_cli_nonexistent_path` | Run with `./does-not-exist` | Exit code 1. Output contains "does not exist". |
| INT-07 | `test_cli_file_not_directory` | Run with path to a file | Exit code 1. Output contains "is a file, not a directory". |
| INT-08 | `test_cli_no_supported_language` | Run on `fixtures/no_language/` | Exit code 1. Output contains "No supported language detected". |
| INT-09 | `test_cli_verbose_mode` | Run with `--verbose` | Exit code 0. Output contains detailed analysis steps. |
| INT-10 | `test_cli_quiet_mode` | Run with `--quiet` | Exit code 0. Stdout is minimal (only file paths or nothing). |
| INT-11 | `test_cli_version` | Run with `--version` | Prints version string. Exits. |
| INT-12 | `test_cli_help` | Run with `--help` | Output contains usage example, all flags. |

#### `test_full_pipeline.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| FP-01 | `test_python_django_full` | Full pipeline on `fixtures/python_django/` | >= 5 skill files generated. Each file between 20-150 lines. Content references project-specific paths. |
| FP-02 | `test_typescript_nextjs_full` | Full pipeline on `fixtures/typescript_nextjs/` | >= 5 skill files generated. TypeScript-specific patterns present. |
| FP-03 | `test_go_api_full` | Full pipeline on `fixtures/go_api/` | >= 5 skill files generated. Go idioms (error handling, cmd/ layout) present. |
| FP-04 | `test_rust_cli_full` | Full pipeline on `fixtures/rust_cli/` | >= 5 skill files generated. Rust patterns (Result types, Cargo) present. |
| FP-05 | `test_java_spring_full` | Full pipeline on `fixtures/java_spring/` | >= 5 skill files generated. Spring/Maven patterns present. |
| FP-06 | `test_polyglot_full` | Full pipeline on `fixtures/polyglot/` | Skills for both Python and TypeScript. Languages listed in skill content. |
| FP-07 | `test_all_formats_generated` | Full pipeline with `--format all` | `.claude/skills/`, `.cursor/rules/`, and `AGENTS.md` all present. Cursor files have valid YAML front matter. |
| FP-08 | `test_generated_content_is_project_specific` | Full pipeline on any fixture | No skill file contains only generic content. Every file references at least one actual path or identifier from the fixture. |

#### `test_idempotency.py`

| Test ID | Test Name | Description | Assertions |
|---|---|---|---|
| IDEM-01 | `test_double_run_identical_output` | Run full pipeline twice on same fixture | All output files are byte-for-byte identical between runs. |
| IDEM-02 | `test_orphan_removed_on_rerun` | Run once (produces `testing.md`), modify fixture to remove tests, run again | `testing.md` is deleted. Other files unchanged. |
| IDEM-03 | `test_agents_md_section_replaced` | Run twice with different analysis results | AGENTS.md content between delimiters reflects second run. Content outside delimiters is unchanged. |
| IDEM-04 | `test_hand_edited_file_preserved` | Place a hand-edited skill file (no header), run skillgen | Hand-edited file is not overwritten. New generated files are created alongside it. |

### 9.4 Coverage Requirements

- **Target:** >= 80% line coverage (measured by `pytest --cov=skillgen`).
- **Critical paths requiring 100% coverage:**
  - `cli.py`: All exit code paths (0, 1, 2).
  - `writer.py`: Atomic write, orphan cleanup, AGENTS.md delimiter handling.
  - `models.py`: All data structure creation and property accessors.
- **Acceptable gaps (may be < 80%):**
  - `renderer.py`: Rich output formatting is hard to unit test; integration tests cover it.
  - `generator.py` LLM mode: Tested via mocked API calls only; actual API calls are not part of CI.

### 9.5 CI Configuration

```yaml
# .github/workflows/test.yml (conceptual)
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev,ast]"
      - run: pytest --cov=skillgen --cov-report=xml --cov-fail-under=80
      - run: ruff check skillgen/ tests/
      - run: ruff format --check skillgen/ tests/
      - run: mypy skillgen/
```

---

*End of technical specification.*
