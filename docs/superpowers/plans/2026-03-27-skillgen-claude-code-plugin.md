# `/skillgen` Claude Code Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a `/skillgen` Claude Code slash command that analyzes any codebase by reading representative files and generates `.claude/skills/*.md` files using Claude's semantic understanding.

**Architecture:** A single skill directory at `.claude/skills/skillgen/` containing `SKILL.md` (the main prompt, ~400 lines) plus supporting files for the enrich subcommand. Uses YAML frontmatter for metadata, `$ARGUMENTS` for subcommand dispatch, and dynamic context injection (`` !`command` ``) for project detection. Claude follows the prompt's phased instructions: detect → sample → read → extract → write.

**Tech Stack:** Claude Code skill system (markdown + YAML frontmatter). No Python dependencies. Uses Glob, Read, Write, Grep, Bash tools that Claude Code provides natively.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `.claude/skills/skillgen/SKILL.md` | Create | Main slash command — detection, sampling, extraction, writing |
| `.claude/skills/skillgen/enrich.md` | Create | Supporting file — enrich subcommand prompt and index URL |

---

### Task 1: Create the Skill Directory and Frontmatter

**Files:**
- Create: `.claude/skills/skillgen/SKILL.md`

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p .claude/skills/skillgen
```

- [ ] **Step 2: Write the frontmatter and command router**

Write the opening of `.claude/skills/skillgen/SKILL.md`:

```markdown
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

You are an expert code analyst. Your job is to read representative files from this codebase, extract coding conventions with specific evidence, and write skill files to `.claude/skills/`.

**Context budget warning:** This skill reads 15-20 source files. Run at the start of a session or in a dedicated session. The generated skill files persist for all future sessions.

## Command Router

- If `$ARGUMENTS` is empty or "save": run the **Full Analysis** below
- If `$ARGUMENTS` is "enrich": run the **Community Enrichment** section at the bottom
- Otherwise: respond "Unknown subcommand. Use `/skillgen`, `/skillgen save`, or `/skillgen enrich`."
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): create /skillgen skill directory with frontmatter and router"
```

---

### Task 2: Write Phase 1 — Project Detection

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md`

- [ ] **Step 1: Add Phase 1 detection instructions**

Append to `SKILL.md`:

```markdown
---

## Full Analysis

### Phase 1: Detect Project Shape

Scan the project to understand its language stack and tooling. Do ALL of the following:

**1a. Find source files:**
Use Glob to discover what languages are present:
- `**/*.py` — Python
- `**/*.ts` and `**/*.tsx` — TypeScript
- `**/*.js` and `**/*.jsx` — JavaScript
- `**/*.go` — Go
- `**/*.rs` — Rust
- `**/*.java` — Java
- `**/*.cpp`, `**/*.cc`, `**/*.h` — C++

Count files per language. The primary language has the most files. Ignore files in `node_modules/`, `vendor/`, `__pycache__/`, `dist/`, `build/`, `.git/`, `target/`, `.venv/`, `venv/`.

**1b. Read manifest and config files:**
Read EACH of these that exists (they're small — read fully):
- `pyproject.toml` — Python project config, ruff/mypy settings in `[tool.*]` sections
- `package.json` — JS/TS dependencies, scripts, framework detection
- `tsconfig.json` — TypeScript configuration
- `go.mod` — Go module and dependencies
- `Cargo.toml` — Rust crate and dependencies
- `pom.xml` or `build.gradle` — Java build config
- `ruff.toml` — Python linter/formatter settings (line-length, select rules, quote-style)
- `.prettierrc` or `.prettierrc.json` — JS/TS formatter settings
- `.eslintrc.json` or `.eslintrc.js` — JS/TS linter config
- `mypy.ini` — Python type checker config
- `.golangci.yml` or `.golangci.yaml` — Go linter config

**1c. Identify frameworks:**
From manifest contents, detect frameworks: Django, FastAPI, Flask, Express, Next.js, React, Vue, Angular, Spring, Gin, Actix, Tokio, etc.

**1d. Record what you found:**
Before proceeding, state:
```
Detected: [languages] | Frameworks: [frameworks] | Config files: [list]
```
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add Phase 1 project detection instructions"
```

---

### Task 3: Write Phase 2 — Smart File Sampling

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md`

- [ ] **Step 1: Add Phase 2 sampling instructions**

Append to `SKILL.md`:

```markdown
### Phase 2: Smart File Sampling

Select 15-20 representative files to read. The goal is DIVERSITY — different directories, different roles, different aspects of the codebase.

**Selection rules:**

1. **Entry point** (1 file): `main.py`, `app.py`, `index.ts`, `main.go`, `main.rs`, `App.tsx`, or whatever starts the application. Read the first 150 lines.

2. **Config/manifest files** (2-3 files): Already read in Phase 1. No additional reading needed.

3. **Source files from different directories** (5-7 files): Pick one file from each major source directory. Prefer files that are NOT the largest in their directory — mid-sized files are more representative than giant ones. Read the first 200 lines of each.

4. **Test files** (2-3 files): Pick test files from different test directories or testing different modules. Read the first 200 lines of each.

5. **Model/type/schema files** (1-2 files): Files that define data structures — `models.py`, `types.ts`, `schema.go`, etc. Read fully (these are usually compact).

6. **Utility/helper files** (1-2 files): Files in `utils/`, `helpers/`, `lib/`, `pkg/`, `internal/`. Read the first 150 lines.

**Anti-rules (DO NOT):**
- Do NOT pick the largest files — they're often generated, migrations, or data
- Do NOT read more than 200 lines of any single source file
- Do NOT read more than 20 files total
- Do NOT read files in vendored directories, migrations, or generated code
- Do NOT read lock files (package-lock.json, Pipfile.lock, go.sum)

**After selecting, list the files you'll read:**
```
Reading 17 files:
  Entry point:  src/main.py (150 lines)
  Source:       src/api/routes.py (200 lines)
  Source:       src/services/user.py (200 lines)
  Source:       src/models/order.py (full - 89 lines)
  ...
  Test:         tests/test_api.py (200 lines)
  Test:         tests/services/test_user.py (200 lines)
  Config:       pyproject.toml (already read)
```

Now read each file using the Read tool, respecting the line limits above.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add Phase 2 smart file sampling instructions"
```

---

### Task 4: Write Phase 3 — Convention Extraction Checklist

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md`

- [ ] **Step 1: Add Phase 3 extraction checklist**

Append to `SKILL.md`:

```markdown
### Phase 3: Extract Conventions

Now analyze ALL the files you read. For EACH of the 8 categories below, extract conventions with **specific evidence from the actual files you read**. Cite real function names, real class names, real file paths.

**CRITICAL RULES:**
- Every bullet point MUST reference actual code you saw. No generic advice.
- If a category has no detectable patterns, write "No clear conventions detected — skip this category." Do NOT invent patterns.
- Use bold for the key pattern: "Functions follow **verb_noun** pattern"
- Include 3+ real examples for each pattern: `get_user`, `create_order`, `validate_input`
- Note conflicts: "80% snake_case, but `legacyModule.js` uses camelCase"
- Include actual config values: "Configured in ruff.toml: line-length = 100"

**CHECKLIST — do not skip any category:**

#### 1. NAMING CONVENTIONS
Extract from the function definitions, class definitions, and file names you observed:
- Function/method naming pattern (with 3+ examples from files you read)
- Class/type naming pattern (with examples)
- File naming pattern (what convention do filenames follow?)
- Variable conventions (constants UPPER_CASE? private _prefix? etc.)
- Decorator patterns (if applicable: @property, @app.route, etc.)

#### 2. ERROR HANDLING
Extract from try/except/catch blocks, error classes, and error returns you observed:
- Exception/error types used (list the actual types you saw)
- Try/catch patterns (what is caught specifically? bare except anywhere?)
- Custom error/exception classes (if any — name them)
- Error propagation style (re-raise? wrap? return error codes?)

#### 3. TESTING
Extract from test files you read:
- Test framework (pytest, jest, go test, JUnit, etc.)
- Test file location and naming convention
- Fixture/setup patterns (conftest.py, beforeEach, test helpers)
- Assertion style (assert, expect, self.assertEqual, etc.)
- Mocking approach (unittest.mock, jest.mock, testify, etc.)
- Parameterized/table-driven tests (if observed)

#### 4. IMPORTS & DEPENDENCIES
Extract from import statements at the top of files you read:
- Import style (absolute vs relative, from X import Y vs import X)
- Import grouping (stdlib / third-party / local — separated by blank lines?)
- Key dependencies and how they're used
- Re-export patterns (barrel files, __all__)

#### 5. DOCUMENTATION
Extract from docstrings, comments, and module headers you observed:
- Docstring format (Google-style, NumPy-style, JSDoc, Go doc comments, etc.)
- Docstring coverage (most functions have them? only public APIs? none?)
- Module-level docstrings (present or absent?)
- Comment density and style

#### 6. ARCHITECTURE
Extract from the directory structure and file organization you observed:
- Top-level directory layout (what goes where)
- Layer separation (routes → services → models? handlers → repos?)
- Key architectural patterns (dependency injection, middleware chain, etc.)
- Where new code should go (for each type of file)

#### 7. CODE STYLE
Extract from code formatting and config files:
- Line length (from config or observation)
- Quote style (single vs double — which dominates?)
- Semicolons (JS/TS: present or absent?)
- Type annotation coverage (fully typed? partially? none?)
- Trailing commas (used? not used?)
- Formatter/linter (name it, and include key config values from Phase 1)

#### 8. LOGGING & OBSERVABILITY
Extract from logging statements and imports you observed:
- Logging library (logging, structlog, winston, pino, zerolog, log4j, etc.)
- Logger initialization pattern (how is the logger created?)
- Log levels used (which ones appear in the code?)
- Structured vs unstructured (key-value pairs or format strings?)
- If no logging patterns found, state that explicitly.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add Phase 3 convention extraction checklist"
```

---

### Task 5: Write Phase 4 — File Writing Rules

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md`

- [ ] **Step 1: Add Phase 4 writing rules and Phase 5 summary**

Append to `SKILL.md`:

```markdown
### Phase 4: Write Skill Files

For each category where you detected conventions, write a `.claude/skills/<category>.md` file.

**File naming:**
- `naming-conventions.md`
- `error-handling.md`
- `testing.md`
- `imports-and-dependencies.md`
- `documentation.md`
- `architecture.md`
- `code-style.md`
- `logging-and-observability.md`

**Before writing, check for existing files:**
Use Glob to list `.claude/skills/*.md`. For each existing file:
- If it starts with `<!-- Generated by skillgen` → safe to overwrite
- If it does NOT have that marker → it's hand-written. DO NOT overwrite it. Skip that category and note it in the summary.

**File format — every generated file must follow this structure:**

```
<!-- Generated by skillgen | Do not edit — re-run /skillgen to update -->

# [Category Display Name]

## [Subcategory]
- **[Pattern]**: `example1`, `example2`, `example3`
- [Detail with evidence]

## [Next Subcategory]
...
```

**Writing rules:**
- Use the Write tool to create each file
- Create `.claude/skills/` directory if it doesn't exist
- Skip categories with no detected patterns — do not create empty files
- Every line must be backed by evidence from files you read

### Phase 5: Summary

After writing all files, print a summary:

```
/skillgen complete!

Generated [N] skill files in .claude/skills/:
  [filename]    ([line count] lines)
  [filename]    ([line count] lines)
  ...

Skipped: [categories with no patterns or hand-written files]

These conventions are now active for this session and all future sessions.
To share with your team: git add .claude/skills/ && git commit -m "Add AI skill files"

Tip: For Cursor rules and AGENTS.md, use the CLI: pip install skillgen && skillgen .
```
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add Phase 4 write rules and Phase 5 summary"
```

---

### Task 6: Write the Enrich Subcommand

**Files:**
- Create: `.claude/skills/skillgen/enrich.md`
- Modify: `.claude/skills/skillgen/SKILL.md`

- [ ] **Step 1: Create the enrich supporting file**

Write `.claude/skills/skillgen/enrich.md`:

```markdown
# Community Skill Enrichment

## Index URL
https://raw.githubusercontent.com/skillgen/skill-index/main/index.json

## Index Format
The index is a JSON file with this structure:
```json
{
  "version": 1,
  "skills": [
    {
      "id": "python-fastapi",
      "name": "FastAPI Conventions",
      "language": "python",
      "framework": "FastAPI",
      "categories": ["architecture", "error-handling", "testing"],
      "path": "skills/python/fastapi.md",
      "description": "Router organization, dependency injection, Pydantic models"
    }
  ]
}
```

## Skill Content URL Pattern
https://raw.githubusercontent.com/skillgen/skill-index/main/{path}

Where `{path}` is the `path` field from the index entry (e.g., `skills/python/fastapi.md`).
```

- [ ] **Step 2: Add enrich section to SKILL.md**

Append to the end of `SKILL.md`:

```markdown
---

## Community Enrichment

This section runs when the user invokes `/skillgen enrich`.

Read the enrichment reference: [enrich.md](enrich.md)

### Step 1: Detect Project (Quick)

If you haven't already run the full analysis in this session, do a quick detection:
- Glob for source files to identify languages
- Read manifest files to identify frameworks
- List which `.claude/skills/*.md` files already exist (these are "covered" categories)

### Step 2: Fetch Community Index

Use Bash to fetch the index:
```
curl -sf https://raw.githubusercontent.com/skillgen/skill-index/main/index.json
```

If curl fails, report: "Could not reach the community skill index. Check your network connection." and stop.

Parse the JSON response.

### Step 3: Match Skills

For each skill in the index:
1. **Language must match** one of the detected languages
2. **Framework must match** (if the skill specifies one) one of the detected frameworks. If framework is null, the skill applies to all projects of that language.
3. **Category filter**: skip skills whose categories are ALL already covered by existing `.claude/skills/*.md` files

### Step 4: Evaluate Fit

For each matched skill:
1. Fetch the skill content: `curl -sf https://raw.githubusercontent.com/skillgen/skill-index/main/{path}`
2. Read 2-3 relevant local files that relate to the skill's categories
3. Compare and evaluate:
   - **Aligns** (checkmark): the community skill matches patterns you see in the codebase
   - **Conflicts** (warning): the community skill recommends something different from what the codebase does — explain the specific conflict
   - **Fills gap** (plus): the community skill covers something the codebase doesn't have yet

### Step 5: Present Findings

Show the user a numbered list:

```
Found [N] community skills for [Language] + [Framework]:

1. [Skill Name] ([categories])
   [fit evaluation — aligns/conflicts/fills gap with specifics]

2. [Skill Name] ([categories])
   [fit evaluation]

Which would you like to install? (1,2,3 / all / none)
```

Wait for the user's response.

### Step 6: Install Selected Skills

For each selected skill:
1. Create `.claude/skills/community/` directory if needed
2. Write the skill content with a source header:

```markdown
<!-- Source: skillgen/skill-index | Community skill, not derived from your code -->
<!-- Skill: [id] | Fetched: [today's date] -->

[skill content]
```

3. Report what was written:
```
Installed [N] community skills:
  .claude/skills/community/[name].md ([lines] lines)
  ...

To share with your team: git add .claude/skills/community/
```
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/skillgen/
git commit -m "feat(plugin): add /skillgen enrich subcommand with community skill evaluation"
```

---

### Task 7: Manual Smoke Tests

**Files:** None (testing the skill by running it)

- [ ] **Step 1: Test `/skillgen` on the skillgen project itself**

Run: Type `/skillgen` in Claude Code in this project directory.

Verify:
- Phase 1 detects Python, no frameworks
- Phase 2 samples ~15 files from different directories
- Phase 3 extracts all 8 categories (or explicitly skips empty ones)
- Phase 4 writes `.claude/skills/*.md` files with the marker header
- Phase 5 prints a summary
- Generated skill files are specific to this codebase (mention actual function names, actual config values)
- No generic advice like "always use type hints" without evidence

- [ ] **Step 2: Test that hand-written skills are preserved**

Before running, create a hand-written skill:
```bash
echo "# My Custom Rules\n\nAlways use spaces, never tabs." > .claude/skills/custom-rules.md
```

Run `/skillgen` again. Verify `custom-rules.md` is NOT overwritten (no `<!-- Generated by skillgen` marker).

- [ ] **Step 3: Test `/skillgen enrich`**

Run: Type `/skillgen enrich` in Claude Code.

Verify:
- Fetches the index (or reports network failure gracefully)
- Matches skills by language
- Reports findings with fit evaluation
- If user selects skills, writes to `.claude/skills/community/`

- [ ] **Step 4: Test unknown subcommand**

Run: Type `/skillgen foobar`

Verify: Shows "Unknown subcommand" message with valid options.

- [ ] **Step 5: Final commit**

```bash
git add .claude/skills/skillgen/
git commit -m "feat: /skillgen Claude Code plugin — analyze codebase and generate skill files

Adds /skillgen slash command for Claude Code that:
- Reads representative source files directly (no regex/tree-sitter)
- Extracts conventions using Claude's semantic understanding
- Writes evidence-backed .claude/skills/*.md files
- Supports /skillgen enrich for community skill evaluation
- Never overwrites hand-written skill files
- Works with zero dependencies (pure markdown skill)"
```

---

## Self-Review Checklist

**Spec coverage:**
- Phase 1 (detect): Task 2
- Phase 2 (sample): Task 3
- Phase 3 (extract): Task 4 — includes all 8 categories with the checklist
- Phase 4 (write): Task 5 — includes marker safety, format spec
- Phase 5 (summary): Task 5
- Enrich subcommand: Task 6 — index fetch, matching, fit eval, interactive approval
- Context budget warning: Task 1 frontmatter
- Command router: Task 1
- Non-destructive writes: Task 5 marker check
- Argument support: Task 1 frontmatter `argument-hint`

**Placeholder scan:** No TBD or TODO found. All prompt text is complete.

**Type consistency:** Not applicable — this is a markdown prompt, not code. Verified: file paths are consistent (`.claude/skills/skillgen/SKILL.md`), category names match between extraction and writing, marker text matches between write and overwrite-check.
