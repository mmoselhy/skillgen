# Contributing to skillgen

Thank you for your interest in contributing to skillgen. This guide covers everything you need to get started.

## Prerequisites

- **Python 3.11+** (3.11 or 3.12 recommended)
- **pip** (comes with Python)
- **Git**

## Development Setup

```bash
# 1. Fork and clone the repo
git clone https://github.com/<your-username>/skillgen.git
cd skillgen

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Verify the installation
skillgen --help
```

## Running Tests

```bash
# Run the full test suite
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=skillgen --cov-report=term-missing

# Run a specific test file
pytest tests/test_detector.py -v

# Run a specific test by name
pytest tests/ -k "test_detect_python" -v
```

All tests must pass before submitting a PR. The CI pipeline runs tests on Python 3.11 and 3.12.

## Running Lints

```bash
# Lint with ruff
ruff check skillgen/ tests/

# Format check with ruff
ruff format --check skillgen/ tests/

# Auto-fix lint issues
ruff check --fix skillgen/ tests/

# Auto-format
ruff format skillgen/ tests/

# Type check with mypy
mypy skillgen/ --ignore-missing-imports
```

The project uses strict mypy settings. All public functions must have type annotations.

## Code Style Guidelines

- **Formatter/Linter:** [ruff](https://docs.astral.sh/ruff/) with a line length of 100 characters.
- **Type checking:** [mypy](https://mypy.readthedocs.io/) in strict mode.
- **Imports:** Group in order -- standard library, third-party, local. Use `from __future__ import annotations` in every module.
- **Naming:** `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- **Docstrings:** Every public module, class, and function must have a docstring. Use a concise single-line format for short descriptions.
- **Error handling:** Catch specific exception types. Use `raise ... from err` to preserve tracebacks. Never use bare `except:`.
- **Testing:** Use pytest. One behavior per test function. Descriptive test names (`test_detect_python_from_pyproject_toml`).

## PR Process

1. **Fork** the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feature/my-change
   ```

2. **Make your changes.** Keep commits focused -- one logical change per commit.

3. **Write or update tests** for any new or changed functionality.

4. **Run the full check suite** before pushing:
   ```bash
   ruff check skillgen/ tests/
   ruff format --check skillgen/ tests/
   mypy skillgen/ --ignore-missing-imports
   pytest tests/ -v
   ```

5. **Push and open a pull request** against `main`. Include:
   - A clear description of what the PR does and why.
   - A note on how to test the change.
   - Any related issue numbers.

6. **Address review feedback.** PRs require passing CI checks and at least one approval before merging.

## Architecture Overview

skillgen is a four-stage pipeline. Each stage is a separate module with a clean data interface:

| Module | Responsibility | Input | Output |
|---|---|---|---|
| `skillgen/cli.py` | CLI entry point (Typer). Parses flags, validates paths, orchestrates the pipeline. | Command-line arguments | Exit code |
| `skillgen/detector.py` | Walks the file tree, counts extensions, reads manifests, detects languages and frameworks. | `Path` (project root) | `ProjectInfo` |
| `skillgen/analyzer.py` | Samples source files and extracts code patterns across 8 categories using regex heuristics. | `ProjectInfo` | `AnalysisResult` |
| `skillgen/generator.py` | Renders skill file content from patterns. Local (rule-based) by default, with optional LLM enhancement. | `AnalysisResult` | `GenerationResult` |
| `skillgen/writer.py` | Writes files atomically to `.claude/skills/`, `.cursor/rules/`, and `AGENTS.md`. Handles dry-run and orphan cleanup. | `GenerationResult` | `list[WrittenFile]` |
| `skillgen/renderer.py` | Terminal UI: spinners, summary tables, diff output, stats panels (Rich). | Various result types | Terminal display |
| `skillgen/models.py` | Shared data structures (dataclasses and enums) used across all modules. | -- | -- |

### Adding a New Language

The architecture is designed to make adding languages straightforward:

1. Add the language to the `Language` enum in `models.py` with its extensions.
2. Add extension mappings in `detector.py` (`EXTENSION_MAP`).
3. Add manifest mappings in `detector.py` (`MANIFEST_MAP`).
4. Add framework markers in `detector.py` (`FRAMEWORK_MARKERS`), if applicable.
5. Add language-specific regex extractors in `analyzer.py`.
6. Add language-specific rendering guidance in `generator.py`.
7. Add tests for the new language in `tests/`.

### Adding a New Pattern Category

1. Add the category to the `PatternCategory` enum in `models.py`.
2. Add an extractor function in `analyzer.py`.
3. Add a renderer function in `generator.py` and register it in `_CATEGORY_RENDERERS`.
4. Add tests.

## Questions?

Open an issue on GitHub or start a discussion. We're happy to help.
