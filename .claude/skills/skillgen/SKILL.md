---
name: skillgen
description: Analyze this codebase and generate AI agent skill files. Extracts naming, error handling, testing, import, documentation, architecture, style, and logging conventions by reading representative source files.
argument-hint: "[enrich|save]"
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash(ls *)
  - Bash(head *)
  - Bash(wc *)
  - Bash(find *)
  - Bash(curl *)
  - Bash(cat *)
---

# /skillgen — Codebase Convention Analyzer

> **Context budget:** If the `skillgen` CLI is installed (`pip install skillgen-ai`), this skill uses hybrid mode — CLI stats + 5-8 files (~1,700 lines of context). Without the CLI, standalone mode reads 15-20 files (~10,000 lines). Either way, run at session start or in a dedicated session.

## Command Router

Inspect `$ARGUMENTS` and branch:

| `$ARGUMENTS` value | Action |
|---|---|
| *(empty)* or `save` | Run **Full Analysis** (Phases 1–5 below) |
| `enrich` | Run **Community Enrichment** (see bottom section) |
| anything else | Reply: "Unknown subcommand. Use `/skillgen`, `/skillgen save`, or `/skillgen enrich`." and stop. |

---

## Full Analysis

Execute phases in order. Start with Phase 0 to detect the mode, then follow the appropriate path. Print progress headers as you go.

---

### Phase 0: Detect Mode (Hybrid vs Standalone)

**Goal:** Check if the `skillgen` CLI is installed. If yes, use it for statistical analysis and read fewer files. If no, fall back to standalone mode.

Run this command:

```bash
skillgen --version
```

**If the command succeeds (exit code 0):**

1. Print: `skillgen CLI detected. Using hybrid mode: CLI stats + Claude semantics.`
2. Run: `skillgen . --json`
3. Parse the JSON output. You now have:
   - `project_info`: languages, frameworks, file counts, manifest paths
   - `categories`: dict of up to 8 categories, each with `entries` containing `prevalence`, `file_count`, `total_files`, `confidence`, `evidence`, `conflict`
   - `config_settings`: tool configuration values (e.g., `ruff.line-length`, `prettier.singleQuote`, `mypy.strict`)
   - `config_files_parsed`: which config files were read
   - `files_analyzed`: total files the CLI scanned
4. If the JSON appears truncated (does not end with `}`) or fails to parse, print "CLI output was invalid. Falling back to standalone mode." and proceed to Phase 1.
5. Otherwise, **skip Phase 1 entirely** and proceed to **Phase 2 (Hybrid Sampling)**.

**If the command fails (not found, error):**

1. Print: `skillgen CLI not installed. Using standalone mode (reads more files, uses more context).`
2. Print: `Tip: pip install skillgen-ai for faster, more accurate analysis.`
3. Proceed to **Phase 1** (standalone detection below).

---

### Phase 1: Detect Project Shape

**Goal:** Determine what languages, frameworks, and tooling this project uses.

#### 1a. Count source files by language

Glob for each extension family. Exclude these directories in every glob and search throughout the entire skill: `node_modules/`, `vendor/`, `__pycache__/`, `dist/`, `build/`, `.git/`, `target/`, `.venv/`, `venv/`, `.tox/`, `env/`, `.mypy_cache/`, `.pytest_cache/`, `.next/`, `coverage/`.

| Language group | Glob patterns |
|---|---|
| Python | `**/*.py` |
| TypeScript | `**/*.ts`, `**/*.tsx` |
| JavaScript | `**/*.js`, `**/*.jsx` |
| Go | `**/*.go` |
| Rust | `**/*.rs` |
| Java | `**/*.java` |
| C/C++ | `**/*.cpp`, `**/*.cc`, `**/*.h`, `**/*.c` |

Count files per group. The group with the most files is the **primary language**. Record all groups with at least 1 file.

#### 1b. Read manifest files

Attempt to read each of these at the project root (skip those that do not exist):
- `pyproject.toml`
- `package.json`
- `tsconfig.json`
- `go.mod`
- `Cargo.toml`
- `pom.xml`
- `build.gradle`
- `Makefile`
- `CMakeLists.txt`

From their contents, detect frameworks:
- **Python:** look for `[tool.poetry]`, `[project]` dependencies — Django, Flask, FastAPI, Click, Typer, Pydantic, SQLAlchemy, pytest, etc.
- **TypeScript/JS:** look at `dependencies` and `devDependencies` — React, Next.js, Express, Nest, Vite, Jest, Vitest, Mocha, etc.
- **Go:** look at `require` block — Gin, Echo, Cobra, etc.
- **Rust:** look at `[dependencies]` — Actix, Axum, Tokio, Clap, Serde, etc.
- **Java:** look at dependencies — Spring Boot, Quarkus, JUnit, etc.

#### 1c. Read config/linter files

Attempt to read each (skip missing):
- `ruff.toml`, `pyproject.toml` `[tool.ruff]` section
- `.prettierrc`, `.prettierrc.json`, `.prettierrc.js`
- `.eslintrc.json`, `.eslintrc.js`, `.eslintrc.yml`, `eslint.config.js`
- `mypy.ini`, `pyproject.toml` `[tool.mypy]` section
- `.golangci.yml`, `.golangci.yaml`
- `rustfmt.toml`
- `.editorconfig`
- `tox.ini`

#### 1d. Print detection summary

Print exactly one line in this format:

```
Detected: Python (42 files), TypeScript (12 files) | Frameworks: FastAPI, Pydantic, pytest | Config: ruff.toml, mypy.ini
```

If no frameworks detected, print `Frameworks: (none)`. If no config files found, print `Config: (none)`.

---

### Phase 2 (Hybrid): Focused Semantic Sampling

> **This section runs only in hybrid mode** (Phase 0 detected the CLI). In standalone mode, skip to the next section.

The CLI already scanned up to 50 files per language and reported statistical patterns. You only need to read files for **semantic understanding** — naming patterns, architectural intent, and contextual guidance that statistics alone can't capture.

Select **5-8 files** (not 15-20):

1. **Entry point** (1 file): Same heuristic as standalone — `main.py`, `index.ts`, etc. Read first 150 lines.
2. **Source files from different directories** (2-3 files): Look at the CLI JSON's `evidence` fields for filenames that appear frequently. Pick files from different directories. Read first 200 lines each.
3. **Test files** (1-2 files): Pick from the CLI's testing category evidence. Read first 200 lines each.
4. **Model/type file** (1 file): Look for `models.py`, `types.ts`, `schema.go` in the CLI evidence. Read fully if under 200 lines.

**Anti-rules still apply:** no generated files, no migrations, no lock files, no vendored code.

Print the file list:
```
Hybrid mode — reading N files for semantic enrichment:
  Entry point:  src/main.py (150 lines)
  Source:       src/services/user.py (200 lines)
  Source:       src/api/routes.py (200 lines)
  Test:         tests/test_api.py (200 lines)
  Model:        src/models/order.py (89 lines, full)
  Config:       (already parsed by CLI)
```

Read all files, then proceed to **Phase 3 (Hybrid Extraction)**.

---

### Phase 2 (Standalone): Smart File Sampling

> **This section runs only in standalone mode** (CLI not detected in Phase 0). In hybrid mode, you already did Phase 2 above.

**Goal:** Select 15–20 representative files that cover the project's breadth without blowing up the context window.

Pick files from these buckets in order, stopping when you reach 20 files total:

#### Bucket 1 — Entry point (1 file)
Look for: `main.py`, `app.py`, `cli.py`, `__main__.py`, `index.ts`, `index.js`, `main.go`, `main.rs`, `App.tsx`, `App.jsx`, `server.ts`, `server.js`.
Read the **first 150 lines**.

#### Bucket 2 — Config files (2–3 files)
These were already read in Phase 1. Do not re-read. Just include them in the count.

#### Bucket 3 — Source files from different directories (5–7 files)
List the top-level source directories (e.g., `src/`, `lib/`, `pkg/`, `app/`, `internal/`, or the project-named directory). Pick **one file per directory**, preferring mid-sized files (50–300 lines) over the largest. Read the **first 200 lines** of each.

Selection heuristic: sort files in each directory by line count, pick the file closest to the median size. Skip files named `__init__.py` or `index.ts`/`index.js` if they are re-export barrels (under 20 lines).

#### Bucket 4 — Test files (2–3 files)
Look in `tests/`, `test/`, `__tests__/`, `spec/`, or files matching `*_test.py`, `*_test.go`, `*.test.ts`, `*.test.js`, `*.spec.ts`, `*.spec.js`. Pick files from **different test directories or testing different modules**. Read the **first 200 lines** of each.

#### Bucket 5 — Model/type/schema files (1–2 files)
Look for: `models.py`, `types.ts`, `types.py`, `schema.py`, `schema.go`, `entities.py`, `interfaces.ts`, `dto.py`, files in a `models/` or `types/` directory. Read **fully if under 200 lines**, else first 200 lines.

#### Bucket 6 — Utility files (1–2 files)
Look in `utils/`, `helpers/`, `lib/`, `pkg/`, `common/`, `shared/`. Pick files that are not trivially small (>20 lines). Read the **first 150 lines**.

#### Anti-rules — Do NOT select:
- The **largest** files in the project (often generated, vendored, or migration dumps)
- More than **200 lines** from any single file
- More than **20 files** total
- Files in vendored, generated, or migration directories (`migrations/`, `generated/`, `__generated__/`, `vendor/`, `node_modules/`)
- Lock files (`package-lock.json`, `poetry.lock`, `Cargo.lock`, `go.sum`, `yarn.lock`, `pnpm-lock.yaml`)
- Binary or asset files

#### Print the sampling plan before reading

Print a numbered list:

```
Reading 17 files:
  1. skillgen/cli.py          (lines 1–150)
  2. pyproject.toml            (already read)
  3. ruff.toml                 (already read)
  ...
```

Then read all the files. Proceed to Phase 3 only after all reads complete.

---

### Phase 3 (Hybrid): Combined Extraction

> **This section runs only in hybrid mode.** In standalone mode, skip to the next section.

You have TWO data sources for each category:
1. **CLI data** — exact statistics: prevalence percentages, file counts, config values, evidence strings, conflict annotations
2. **Your reading** — semantic understanding from the 5-8 files you just read

**Combination rules:**

1. **Quantitative claims MUST come from CLI data:**
   Write: "**82% use snake_case** (14/17 files)"
   NOT: "most functions use snake_case" (vague)

2. **Semantic insight comes from your reading:**
   Write: "specifically the **verb_noun** pattern: `get_user`, `create_order`, `validate_input`"
   NOT: just listing the CLI's evidence strings verbatim

3. **Config values come from CLI data verbatim:**
   Write: "**Configured in ruff:** line-length = 100, select = E, F, W, I, N, UP, B, SIM, RUF"
   (Found in the JSON's `config_settings` dict)

4. **Architectural guidance comes from your reading:**
   Write: "New API endpoints go in `app/routers/` following the existing `APIRouter` pattern"
   (The CLI can't infer this — only you can, from reading the code)

5. **Conflicts — explain with context:**
   If the CLI JSON shows a `conflict` field, explain it using what you observed:
   Write: "82% snake_case, but `legacy/old_api.py` uses camelCase (appears to be pre-refactor code)"

6. **Don't just reformat the JSON.** Add genuine semantic value from your reading. If you can't add anything beyond what the CLI says for a category, use the CLI data as-is — don't pad with generic advice.

7. **Process ALL 8 categories.** Walk through: naming, error handling, testing, imports, documentation, architecture, code style, logging. For each, combine CLI stats + your insight. Also note any patterns your reading revealed that the CLI missed (e.g., decorator conventions, DI patterns).

After extraction, proceed to **Phase 4** (same for both modes).

---

### Phase 3 (Standalone): Convention Extraction Checklist

> **This section runs only in standalone mode.** In hybrid mode, you already did Phase 3 above.

**Goal:** Extract concrete, evidence-based conventions from the files you just read.

#### Critical rules for every bullet you write:

1. **Every bullet MUST reference actual code** from files you read in Phase 2. Cite the file name.
2. **No generic advice.** If you looked for a pattern and did not find it, write: "No clear convention detected" and move to the next sub-category.
3. **Bold the key pattern:** e.g., "Functions follow **verb_noun** naming: `get_user`, `create_order`, `validate_input`"
4. **Include 3+ real examples** from the codebase for each convention.
5. **Note conflicts honestly:** e.g., "80% of files use **snake_case** imports, but `legacyModule.js` uses camelCase"
6. **Include config-derived values:** e.g., "Line length set to **88** in `pyproject.toml` `[tool.ruff]`"
7. If an entire category has no detectable conventions, skip it entirely in the output.

---

#### Category 1: NAMING CONVENTIONS

Extract and document each of these if a pattern exists:

- **Function/method names:** snake_case, camelCase, PascalCase? Verb-noun pattern? Prefixes like `_private`, `is_`, `has_`, `get_`, `set_`?
- **Class names:** PascalCase? Suffixes like `Service`, `Controller`, `Handler`, `Factory`, `Mixin`?
- **File names:** snake_case.py, kebab-case.ts, PascalCase.tsx? Do file names mirror the main export?
- **Variable names:** snake_case, camelCase? Constants in UPPER_SNAKE_CASE?
- **Decorator/attribute usage patterns:** `@app.route`, `@dataclass`, `@property` — how consistently used?

#### Category 2: ERROR HANDLING

- **Exception types:** Built-in exceptions only, or custom exception hierarchy? Where are custom exceptions defined?
- **Try/except patterns:** Broad `except Exception` or specific? Bare `except:` present?
- **Error propagation:** Do functions raise, return error codes, return Result types, or use a custom error wrapper?
- **HTTP/API errors:** Status codes, error response format, error middleware?
- **Logging on error:** Is the pattern `logger.exception()`, `logger.error(..., exc_info=True)`, or silent?

#### Category 3: TESTING

- **Framework:** pytest, unittest, Jest, Vitest, Mocha, Go testing, etc.?
- **File organization:** `tests/` mirrors `src/`? Flat test directory? Co-located tests?
- **Fixtures/setup:** pytest fixtures, setUp/tearDown, beforeEach/afterEach, factory functions?
- **Assertion style:** `assert x == y`, `self.assertEqual`, `expect(x).toBe(y)`, custom matchers?
- **Mocking:** unittest.mock, pytest-mock, jest.mock, testify/mock? What gets mocked?
- **Parameterized tests:** `@pytest.mark.parametrize`, `test.each`, table-driven tests?
- **Coverage or CI config:** Any evidence of coverage thresholds or CI test commands?

#### Category 4: IMPORTS & DEPENDENCIES

- **Import style:** Absolute vs relative? `from x import y` vs `import x`?
- **Import grouping/ordering:** stdlib, third-party, local — separated by blank lines? Enforced by tool?
- **Key dependencies:** List the 5–10 most-used third-party packages based on import frequency.
- **Re-exports:** Does the project use `__init__.py` or `index.ts` barrel files? What do they export?
- **Dependency injection patterns:** Constructor injection, module-level singletons, FastAPI `Depends()`?

#### Category 5: DOCUMENTATION

- **Docstring format:** Google style, NumPy style, reStructuredText, JSDoc, GoDoc?
- **Coverage:** Are all public functions documented, or only some? What percentage roughly?
- **Module-level docs:** Do files start with a module docstring or header comment?
- **Inline comments:** Frequent or rare? Explain "why" or "what"?
- **Type annotations:** Full coverage, partial, or absent? `-> return_type` on functions?

#### Category 6: ARCHITECTURE

- **Directory layout:** Describe the top-level structure and what each directory contains.
- **Layering:** Is there separation between CLI/API, business logic, and data access?
- **Key patterns:** Repository pattern, service layer, dependency injection, event-driven, MVC, etc.?
- **Where new code goes:** Based on existing structure, where should a new feature module be added?
- **Configuration management:** Environment variables, config files, settings module?

#### Category 7: CODE STYLE

- **Line length:** Configured limit, or infer from longest lines in sample.
- **String quotes:** Single or double? Consistent?
- **Semicolons (JS/TS):** Present or omitted?
- **Trailing commas:** In function args, dict/object literals, imports?
- **Type annotations:** Full, partial, or none? `mypy` strictness level?
- **Formatter/linter:** Which tools, what config values are set? (From Phase 1 config files.)
- **Blank line conventions:** Between functions, between classes, between methods?

#### Category 8: LOGGING & OBSERVABILITY

- **Logging library:** `logging`, `structlog`, `loguru`, `winston`, `pino`, `log/slog`, `tracing`?
- **Logger initialization:** Module-level `logger = logging.getLogger(__name__)`, injected, or global?
- **Log levels used:** Which levels appear in the code? Is there a pattern for when each is used?
- **Structured vs unstructured:** Key-value pairs, JSON, or plain string messages?
- **Observability:** Any tracing, metrics, or health check patterns?

---

### Phase 4: Write Skill Files

**Goal:** Persist the extracted conventions as `.claude/skills/*.md` files.

#### 4a. Check for existing files

Glob `.claude/skills/*.md`. For each file found:
- Read the first 3 lines.
- If the file contains `<!-- Generated by skillgen` in those lines, it was previously generated and is **safe to overwrite**.
- If the file does NOT contain that marker, it is **hand-written**. Do NOT overwrite it. Add it to the skip list.

#### 4b. Create the output directory

Run `mkdir -p .claude/skills/` if it does not already exist.

#### 4c. Write each category file

For each of the 8 categories where conventions were detected, write a file using this exact mapping:

| Category | File name |
|---|---|
| Naming Conventions | `naming-conventions.md` |
| Error Handling | `error-handling.md` |
| Testing | `testing.md` |
| Imports & Dependencies | `imports-and-dependencies.md` |
| Documentation | `documentation.md` |
| Architecture | `architecture.md` |
| Code Style | `code-style.md` |
| Logging & Observability | `logging-and-observability.md` |

Each file MUST follow this format exactly:

```markdown
<!-- Generated by skillgen | Do not edit — re-run /skillgen to update -->

# [Category Name]

## [Subcategory Name]
- **[Pattern name]**: `example1`, `example2`, `example3`
- **[Another pattern]**: Description with `inline_code` references

## [Another Subcategory]
- **[Pattern]**: Evidence from `filename.py` — description
```

Rules for file content:
- First line is always the HTML comment marker. No blank line before it.
- Use `#` for the category title, `##` for subcategories, `-` for bullet points.
- Bold the pattern name in each bullet.
- Include inline code for all code references (function names, file names, config values).
- Do not include generic advice. Every line must be grounded in the analysis.
- If a subcategory had no conventions detected, omit that subcategory entirely.
- If an entire category had no conventions detected, do not create the file.

#### 4d. Skip hand-written files

If a file in the skip list would have been written, print: "Skipped [filename] — hand-written file detected (no skillgen marker). Delete the file or add the marker to allow overwriting."

---

### Phase 5: Summary

After all files are written, print a summary based on which mode was used.

**If hybrid mode:**

```
/skillgen complete! (hybrid mode: CLI stats + Claude semantics)

Generated N skill files in .claude/skills/:
  naming-conventions.md      (XX lines)
  error-handling.md          (XX lines)
  ...

Skipped: [list categories skipped — "no patterns" or "hand-written file"]

Powered by skillgen CLI (statistical analysis across NN files) + Claude (semantic enrichment from N files).
To share with your team: git add .claude/skills/ && git commit -m "Add AI skill files"
```

**If standalone mode:**

```
/skillgen complete! (standalone mode)

Generated N skill files in .claude/skills/:
  naming-conventions.md      (XX lines)
  ...

Skipped: [list categories skipped]

These conventions are now active for this and all future sessions.
To share with your team: git add .claude/skills/ && git commit -m "Add AI skill files"

Tip: pip install skillgen-ai for faster, more accurate analysis (hybrid mode).
```

Only list files that were actually written. Adjust counts accordingly.

---

## Community Enrichment

This section runs when `$ARGUMENTS` is `enrich`.

Refer to the supporting file at `.claude/skills/skillgen/enrich.md` for the index URL and JSON schema.

### Step 1: Quick project detection

If Full Analysis was not already run in this session:
- Glob source files and count by language to determine primary language.
- Read manifest files (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`) to detect frameworks.
- Glob `.claude/skills/*.md` and list existing skill files (read first line of each to get the category name).

### Step 2: Fetch the community skill index

Run: `curl -sf https://raw.githubusercontent.com/mmoselhy/skill-index/main/index.json`

If the curl fails (non-zero exit or empty output):
- Print: "Could not reach the community skill index. Check your network connection and try again."
- Stop execution.

Parse the JSON response. It contains a `skills` array. Each skill object has: `id`, `name`, `language`, `framework` (nullable), `categories` (array of strings), `path`, `description`.

### Step 3: Match skills to this project

For each skill in the index:
1. **Language filter:** The skill's `language` must match the project's primary language (or be `"any"`). Skip otherwise.
2. **Framework filter:** If the skill has a `framework` value, it must match one of the detected frameworks. If `framework` is null, it matches any project.
3. **Coverage filter:** Collect the skill's `categories` array. If ALL of those categories already have a corresponding `.claude/skills/{category}.md` file locally, skip the skill — it is fully covered.

Collect all matching skills into a candidate list.

If no candidates match: print "No community skills found for this project's language and framework combination." and stop.

### Step 4: Evaluate each candidate

For each candidate skill (up to 10):
1. Fetch the skill content: `curl -sf https://raw.githubusercontent.com/mmoselhy/skill-index/main/{path}`
2. Read 2–3 local source files relevant to the skill's categories (reuse files from Phase 2 if available, or pick new ones using the same sampling heuristics).
3. Compare the community skill's recommendations against the local codebase patterns.
4. Assign one of three evaluations:
   - **Aligns** (checkmark): The community skill's recommendations match what the codebase already does. Installing it reinforces existing patterns.
   - **Conflicts** (warning): The community skill recommends something different from what the codebase does. Explain the specific conflict (e.g., "Community skill recommends `structlog`, but this project uses `logging` with a custom formatter").
   - **Fills gap** (plus): The community skill covers conventions the codebase does not have yet. Good for establishing new patterns.

### Step 5: Present candidates to user

Print a numbered list:

```
Community skills available for Python + FastAPI:

  1. [+] fastapi-error-responses — Standardized error response format for FastAPI
       Fills gap: No error response conventions detected locally.

  2. [✓] python-logging-structlog — Structured logging with structlog
       Aligns: Project already uses structlog with similar patterns.

  3. [!] python-import-style — Absolute imports with isort grouping
       Conflicts: Project uses relative imports in 60% of files.

Install which? (1,2,3 / all / none):
```

Wait for user input.

### Step 6: Install selected skills

For each skill the user selects:
1. Create directory: `mkdir -p .claude/skills/community/`
2. Write the skill file to `.claude/skills/community/{id}.md` with this header prepended:

```markdown
<!-- Source: skillgen/skill-index | Community skill, not derived from your code -->
<!-- Skill: {id} | Fetched: {YYYY-MM-DD} -->

{original skill content}
```

### Step 7: Print installation summary

```
Installed N community skills:
  .claude/skills/community/fastapi-error-responses.md
  .claude/skills/community/python-logging-structlog.md

These skills are now active alongside your project-specific conventions.
```
