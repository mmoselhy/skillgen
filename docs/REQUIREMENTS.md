# skillgen -- Requirements Document

**Version:** 1.0
**Date:** 2026-03-24
**Status:** Draft
**Author:** Product Management

---

## Product Vision

`skillgen` is a CLI tool that analyzes any codebase and automatically generates AI agent skill files (`.claude/skills/`, `.cursor/rules`, `AGENTS.md`) so that AI coding assistants understand a project's conventions, patterns, and architecture from the first prompt. Today, developers either write these files by hand -- a tedious, error-prone process that most skip entirely -- or they let AI agents hallucinate conventions that don't match the codebase. `skillgen` closes that gap: one command, and every AI tool on the team speaks the project's language.

---

## Target Users and Use Cases

### Persona 1: Solo Developer -- "Alex"

- **Role:** Full-stack developer maintaining 3-5 personal and open-source projects.
- **Pain:** AI assistants generate code that doesn't follow the project's naming conventions, test patterns, or error handling style. Alex wastes time correcting AI output or doesn't use AI at all.
- **Primary Use Case:** Run `skillgen ./my-project` once after cloning or starting a project. Generated skill files immediately improve AI assistant output quality without any manual configuration.

### Persona 2: Tech Lead -- "Priya"

- **Role:** Leads a team of 8 engineers on a large TypeScript monorepo. Uses Claude Code and Cursor across the team.
- **Pain:** Every team member's AI assistant produces inconsistent code. Priya has tried writing `.cursor/rules` manually but they go stale and don't cover all patterns.
- **Primary Use Case:** Run `skillgen` in CI or as a pre-commit hook to keep skill files in sync with the evolving codebase. Use `--diff` to audit what the AI agent "knows" and catch gaps. Commit generated files to the repo so the entire team benefits.

### Persona 3: Open-Source Maintainer -- "Jordan"

- **Role:** Maintains a popular Go library with 50+ contributors.
- **Pain:** New contributors submit PRs that violate undocumented conventions (error wrapping style, test table patterns, package layout). Review cycles are long.
- **Primary Use Case:** Generate an `AGENTS.md` at the repo root so that any contributor using any AI tool gets guidance on the project's conventions. Use `--dry-run` to preview output before committing. Use `--format cursor` to also generate Cursor-specific rules for contributors who use that editor.

### Persona 4: Platform/DevEx Engineer -- "Sam"

- **Role:** Builds internal developer tooling at a mid-size company with 20+ microservices in Python, Go, and Java.
- **Pain:** Needs to roll out AI coding assistants across the org but each repo has different conventions. Writing skill files for every repo is not scalable.
- **Primary Use Case:** Script `skillgen` across all repositories in a batch job. Evaluate output with `--diff` to ensure coverage. Integrate into the internal developer platform so skill files are regenerated on each release.

---

## Functional Requirements

### FR-01: Language and Framework Detection

**Description:** `skillgen` must detect the primary language(s) and framework(s) of a codebase by analyzing file extensions, configuration files, and directory structure. It must not require the user to specify the language.

**Supported languages (v1.0):** Python, TypeScript/JavaScript, Java, Go, Rust, C/C++.

**Detection signals (non-exhaustive):**

| Signal | Example |
|---|---|
| File extensions | `.py`, `.ts`, `.tsx`, `.java`, `.go`, `.rs`, `.cpp`, `.h` |
| Package manifests | `pyproject.toml`, `package.json`, `pom.xml`, `go.mod`, `Cargo.toml`, `CMakeLists.txt` |
| Config files | `tsconfig.json`, `setup.cfg`, `.eslintrc`, `rustfmt.toml` |
| Directory conventions | `src/main/java`, `cmd/`, `internal/`, `tests/`, `__tests__/` |
| Framework markers | `next.config.js`, `django` in requirements, `spring` in pom.xml, `actix` in Cargo.toml |

**Acceptance Criteria:**

1. Given a codebase with a single dominant language, `skillgen` correctly identifies the language and framework in >= 95% of cases (measured against a test suite of 50 public repositories).
2. Given a polyglot codebase (e.g., Python backend + TypeScript frontend), `skillgen` identifies all languages that comprise >= 10% of the codebase by file count.
3. Detection completes in < 2 seconds for codebases up to 100,000 files.
4. If no supported language is detected, `skillgen` exits with a clear error message: "No supported language detected. Supported: Python, TypeScript, Java, Go, Rust, C++."

---

### FR-02: Code Pattern Analysis

**Description:** `skillgen` must analyze the codebase to extract concrete, project-specific patterns in the following categories. Analysis must use AST parsing where available and fall back to regex-based heuristics otherwise.

**Pattern categories:**

| Category | What to extract | Example output |
|---|---|---|
| **Naming conventions** | Variable casing (snake_case, camelCase, PascalCase), file naming, module/package naming | "Functions use snake_case. Classes use PascalCase. Files use kebab-case." |
| **Error handling** | Try/catch vs. Result types, custom error classes, error wrapping patterns, panic/unwrap usage | "Errors are wrapped with `fmt.Errorf("operation: %w", err)`. Never use `panic` outside of tests." |
| **Testing patterns** | Test framework, file naming, fixture patterns, mocking approach, table-driven tests | "Tests use pytest with fixtures in `conftest.py`. Mocking uses `unittest.mock.patch`." |
| **Import/module style** | Absolute vs. relative imports, import grouping, barrel files, re-exports | "Imports are grouped: stdlib, third-party, local. Relative imports are never used." |
| **Documentation style** | Docstring format, comment conventions, JSDoc/Javadoc patterns | "All public functions have Google-style docstrings with Args, Returns, and Raises sections." |
| **Architecture patterns** | Directory layout, dependency injection, layered architecture, module boundaries | "Repository pattern: `src/repositories/` for data access, `src/services/` for business logic." |
| **Code style** | Max line length, trailing commas, semicolons, quote style, formatter/linter in use | "Black formatter, line length 88. isort for import sorting." |
| **Logging and observability** | Logger usage, structured logging, log levels | "Structured logging via `structlog`. All log calls include a `request_id` field." |

**Acceptance Criteria:**

1. For each detected language, `skillgen` extracts patterns from at least 5 of the 8 categories listed above.
2. Each extracted pattern includes at least one concrete code example drawn from the actual codebase (not a generic example).
3. Pattern analysis samples a statistically representative subset of files: at minimum 30 files or 20% of files in the language (whichever is smaller), selected from diverse directories.
4. Pattern conflicts are reported (e.g., "80% of functions use snake_case, 20% use camelCase") rather than silently picking one.
5. Analysis completes in < 30 seconds for codebases up to 100,000 files.

---

### FR-03: Skill File Generation

**Description:** `skillgen` must generate between 5 and 8 skill files per codebase. Each skill file must be scoped to a specific concern (not one monolithic file) and must be directly usable by the target AI tool without modification.

**Required skill files (generate all that apply based on detected patterns):**

1. **code-style** -- Naming conventions, formatting, line length, quote style.
2. **error-handling** -- How to create, wrap, propagate, and log errors.
3. **testing** -- Test framework, file organization, fixture patterns, assertion style, coverage expectations.
4. **architecture** -- Directory layout, module boundaries, dependency flow, where new code goes.
5. **imports-and-dependencies** -- Import ordering, grouping, absolute vs. relative, approved external packages.
6. **documentation** -- Docstring format, comment style, README conventions.
7. **logging-and-observability** -- Logger setup, structured fields, log level usage.
8. **api-patterns** -- (if applicable) Request/response patterns, endpoint naming, serialization, validation.

**Acceptance Criteria:**

1. Given a Python/Django codebase, `skillgen` generates at least 5 skill files covering code-style, error-handling, testing, architecture, and documentation.
2. Each generated skill file is between 20 and 150 lines. Files shorter than 20 lines indicate insufficient analysis; files longer than 150 lines are too verbose for AI context windows.
3. Every skill file begins with a one-sentence summary of its purpose (e.g., "This project uses pytest with fixtures defined in conftest.py files at each directory level.").
4. Skill files reference actual paths, class names, and patterns from the analyzed codebase -- not generic boilerplate.
5. No skill file is generated for a category where fewer than 3 concrete patterns were detected. It is better to skip than to emit vague guidance.

---

### FR-04: Multi-Format Output

**Description:** `skillgen` must output skill files in three formats, each conforming to the conventions of its target AI tool.

**Formats:**

| Format | Output location | File structure | Notes |
|---|---|---|---|
| **Claude** | `.claude/skills/<skill-name>.md` | One Markdown file per skill. Front matter with `name` and `description` fields. | Must conform to Claude Code skill file spec. |
| **Cursor** | `.cursor/rules/<skill-name>.mdc` | One `.mdc` file per skill. YAML front matter with `description`, `globs`, and `alwaysApply` fields. | `globs` must match relevant file extensions (e.g., `*.py` for Python skills). `alwaysApply: true` for architecture and code-style; `false` for language-specific skills. |
| **AGENTS.md** | `AGENTS.md` at repo root | Single Markdown file. H2 headings per skill category. | Must be human-readable as well as AI-parseable. Append to existing AGENTS.md if present (do not overwrite). |

**Acceptance Criteria:**

1. `--format claude` generates only `.claude/skills/` files. `--format cursor` generates only `.cursor/rules/` files. `--format all` (the default) generates all three formats.
2. Generated `.mdc` files are valid YAML front matter + Markdown body. Validated by parsing the front matter as YAML without errors.
3. If `.claude/skills/` or `.cursor/rules/` directories do not exist, `skillgen` creates them.
4. If an `AGENTS.md` already exists, `skillgen` appends a clearly delimited section (`<!-- skillgen:start -->` / `<!-- skillgen:end -->`) and replaces only that section on subsequent runs. Content outside the delimiters is never modified.
5. Generated file paths are printed to stdout after writing, one per line.

---

### FR-05: CLI Interface and UX

**Description:** The primary interface is a single command: `skillgen <path>`. The tool must provide a polished terminal experience with clear progress indication, colorized output, and helpful error messages.

**Command syntax:**

```
skillgen <path> [flags]

Arguments:
  <path>    Path to the codebase to analyze. Defaults to "." if omitted.

Flags:
  --format <claude|cursor|all>   Target AI tool format. Default: all.
  --diff                         Show what the AI agent learns vs. a blank-slate agent.
  --dry-run                      Preview generated skill files without writing to disk.
  --verbose                      Show detailed analysis steps.
  --quiet                        Suppress all output except errors.
  --version                      Print version and exit.
  --help                         Print help and exit.
```

**Acceptance Criteria:**

1. `skillgen ./my-project` with no flags detects languages, analyzes patterns, generates all formats, and writes files in a single invocation. The user should not need to answer prompts or provide additional input.
2. Terminal output displays a progress sequence: (a) "Scanning files...", (b) "Detecting languages...", (c) "Analyzing patterns...", (d) "Generating skills...", (e) summary table of generated files. Each phase shows a spinner or progress bar if it takes > 1 second.
3. The summary table at completion lists each generated file path, its format (Claude/Cursor/AGENTS.md), and its size in lines.
4. If the target path does not exist or is not a directory, `skillgen` exits with code 1 and a message: "Error: <path> is not a directory."
5. If the target path is a file (not a directory), `skillgen` exits with code 1 and a message: "Error: <path> is a file, not a directory. Point skillgen at a project root."
6. `skillgen` respects `.gitignore` and does not analyze files in `node_modules/`, `vendor/`, `__pycache__/`, `.git/`, `build/`, `dist/`, or `target/` directories.
7. Exit codes: 0 = success, 1 = user error (bad path, no languages detected), 2 = internal error.

---

### FR-06: Diff Mode (`--diff`)

**Description:** The `--diff` flag outputs a human-readable comparison showing what an AI agent would "know" about the project with skillgen-generated files versus without them (blank-slate). This helps users evaluate the value of the generated skills and identify coverage gaps.

**Output structure:**

```
=== Diff: What the AI Agent Learns ===

Category            | Without skillgen        | With skillgen
--------------------|-------------------------|------------------------------------------
Naming conventions  | (no guidance)           | snake_case functions, PascalCase classes
Error handling      | (no guidance)           | Wrap with fmt.Errorf, never panic
Testing             | (no guidance)           | Table-driven tests, testify assertions
Architecture        | (no guidance)           | cmd/ for entrypoints, internal/ for libs
...
```

**Acceptance Criteria:**

1. `--diff` outputs a table with at least one row per generated skill category.
2. The "Without skillgen" column always shows "(no guidance)" or, if existing skill files are detected, summarizes their content.
3. The "With skillgen" column shows a one-line summary of the key patterns for that category.
4. `--diff` can be combined with `--dry-run` (show diff without writing files).
5. `--diff` can be combined with `--format` (show diff only for the specified format).
6. Output is colorized in terminals that support it (green for new guidance, yellow for updated guidance).

---

### FR-07: Dry Run Mode (`--dry-run`)

**Description:** The `--dry-run` flag runs the full analysis and generation pipeline but prints the generated skill file contents to stdout instead of writing them to disk. No files are created or modified.

**Acceptance Criteria:**

1. `--dry-run` produces identical content to a normal run, differing only in that nothing is written to the filesystem.
2. Each file's content is preceded by a header: `--- <file-path> (dry run, not written) ---`.
3. Files are separated by a blank line.
4. `--dry-run` exits with code 0 if generation succeeds, regardless of filesystem permissions.
5. `--dry-run` combined with `--quiet` outputs only the raw file contents (no headers, no progress), suitable for piping to other tools.

---

### FR-08: Incremental Updates and Idempotency

**Description:** Running `skillgen` multiple times on the same codebase must be safe and predictable. Generated files must be overwritten cleanly, and the tool must not duplicate content or leave orphaned files.

**Acceptance Criteria:**

1. Running `skillgen ./my-project` twice in a row produces identical output (byte-for-byte identical generated files).
2. If a skill category that was previously generated no longer applies (e.g., logging patterns were removed), the corresponding skill file is deleted and the user is notified: "Removed: .claude/skills/logging-and-observability.md (no longer applicable)."
3. Each generated file includes a header comment: `<!-- Generated by skillgen v<version> on <date>. Do not edit manually. -->`.
4. The `AGENTS.md` delimited section is replaced in full on each run; content outside the delimiters is preserved exactly.

---

## Non-Functional Requirements

### NFR-01: Performance

1. **Cold start to completion** for a codebase of 10,000 files must be under 15 seconds on a machine with 4 CPU cores and 8 GB RAM.
2. **Cold start to completion** for a codebase of 100,000 files must be under 60 seconds on the same hardware.
3. **Memory usage** must not exceed 512 MB RSS for a codebase of 100,000 files.
4. File scanning must be parallelized across available CPU cores.

### NFR-02: Reliability

1. `skillgen` must never crash with an unhandled exception. All errors must be caught, logged, and surfaced as a user-friendly message with exit code 2.
2. `skillgen` must never corrupt existing files. If a write fails mid-operation, partially written files must be cleaned up (write to a temp file, then atomic rename).
3. `skillgen` must handle symlinks, binary files, and files with non-UTF-8 encoding gracefully (skip them with a `--verbose` warning, do not abort).

### NFR-03: UX Polish

1. All terminal output must be colorized using ANSI codes when stdout is a TTY, and plain text when piped.
2. Error messages must suggest a corrective action (e.g., "No supported language detected. Supported: Python, TypeScript, Java, Go, Rust, C++. If your project uses a different language, open an issue at <repo-url>.").
3. The `--help` output must include at least one usage example.
4. `skillgen` must complete without requiring network access. All analysis is local.

### NFR-04: Installability

1. `skillgen` must be installable via `pip install skillgen` (Python package on PyPI).
2. `skillgen` must also be runnable via `pipx run skillgen` without prior installation.
3. The only runtime dependency outside the Python standard library must be `rich` (for terminal formatting). AST parsing for non-Python languages must use vendored or zero-dependency parsers, or regex fallback.
4. Supported Python versions: 3.10, 3.11, 3.12, 3.13.

### NFR-05: Testability

1. The codebase must have >= 80% line coverage measured by `pytest --cov`.
2. Every functional requirement must have at least one corresponding integration test that runs `skillgen` against a fixture codebase and asserts on the generated output.
3. Fixture codebases (small, synthetic projects in each supported language) must be checked into the repository under `tests/fixtures/`.

---

## Out of Scope

The following are explicitly **not** in scope for v1.0:

1. **Runtime analysis.** `skillgen` does not run, compile, or execute any code in the target codebase. All analysis is static.
2. **AI/LLM-powered analysis.** `skillgen` does not call any LLM API. All pattern detection is deterministic and rule-based. (An LLM-enhanced mode may be considered for v2.0.)
3. **Language support beyond the six listed.** Ruby, PHP, Swift, Kotlin, Scala, and others are not supported in v1.0. The architecture must make adding new languages straightforward (pluggable analyzer interface), but no commitment is made to ship them.
4. **IDE plugins or GUI.** `skillgen` is CLI-only. No VS Code extension, no web UI.
5. **Skill file editing or merging.** `skillgen` does not provide a way to hand-edit generated files and merge changes on the next run. Users who modify generated files should remove the `<!-- Generated by skillgen -->` header to prevent overwriting (and `skillgen` must respect this -- see FR-08 AC-3).
6. **Monorepo sub-project detection.** `skillgen` analyzes the directory it is pointed at. It does not automatically discover sub-projects within a monorepo. Users should run `skillgen` once per sub-project.
7. **Remote repository analysis.** `skillgen` does not accept GitHub URLs or clone repositories. The user must have the codebase on disk.
8. **Custom rule authoring.** `skillgen` does not provide a DSL or config file for users to define their own pattern detectors. (Planned for v2.0.)

---

## Success Metrics

### Launch Criteria (must be met before v1.0 release)

| Metric | Target | How to measure |
|---|---|---|
| Language detection accuracy | >= 95% on a benchmark of 50 public repos | Automated test suite with expected language labels |
| Pattern extraction coverage | >= 5 of 8 categories populated for each supported language | Run against 10 repos per language, count non-empty categories |
| Skill file quality (human eval) | >= 4.0 / 5.0 average rating | 5 developers rate generated skills for 3 repos each on accuracy, specificity, and usefulness |
| Idempotency | 100% of test cases produce identical output on re-run | Automated test: run twice, diff output, assert empty |
| Performance | < 15s for 10k files, < 60s for 100k files | Benchmark script on CI with synthetic codebases |
| Test coverage | >= 80% line coverage | `pytest --cov` in CI |
| Zero-crash rate | 0 unhandled exceptions across the full benchmark suite | CI run against 50+ repos, assert exit code != 2 |

### Post-Launch Success Indicators (measured 90 days after PyPI release)

| Metric | Target | How to measure |
|---|---|---|
| PyPI installs | >= 5,000 in the first 90 days | PyPI download stats |
| GitHub stars | >= 500 in the first 90 days | GitHub API |
| Repeat usage | >= 30% of installers run it on 2+ projects | Optional anonymous telemetry (opt-in only) |
| Community contributions | >= 3 PRs adding language support or pattern detectors | GitHub PR count |
| User-reported quality issues | < 10 "wrong/misleading skill" issues in 90 days | GitHub issue tracker |

---

## Appendix: Example Generated Skill File

For reference, here is an example of what a generated `.claude/skills/testing.md` file might look like for a Python/pytest codebase:

```markdown
<!-- Generated by skillgen v1.0.0 on 2026-03-24. Do not edit manually. -->

# Testing Conventions

This project uses **pytest** with fixtures defined in `conftest.py` at each directory level.

## Test File Naming
- Test files are named `test_<module>.py` and live alongside source files in `tests/` mirrors.
- Example: `src/auth/login.py` is tested in `tests/auth/test_login.py`.

## Fixture Patterns
- Shared fixtures are in `tests/conftest.py`.
- Domain-specific fixtures are in `tests/<domain>/conftest.py`.
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

---

*End of requirements document.*
