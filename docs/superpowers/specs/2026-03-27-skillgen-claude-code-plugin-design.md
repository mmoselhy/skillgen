# `/skillgen` Claude Code Slash Command

**Date:** 2026-03-27
**Status:** Approved
**Author:** brainstorming session

---

## Summary

A Claude Code slash command that analyzes any codebase by reading representative source files directly, extracts conventions using Claude's semantic understanding, and persists them to `.claude/skills/`. Companion to the standalone CLI — the CLI wins for teams/CI/multi-tool; the plugin wins for individual developer experience.

## Design Principles

1. **Claude IS the analysis engine** — no regex, no tree-sitter, no Python dependencies. Claude reads code and understands it semantically.
2. **One command, immediate value** — `/skillgen` does the right thing with zero configuration.
3. **Evidence-backed only** — every convention line must cite actual code from the project. No generic advice.
4. **Context-aware** — explicitly manages context budget. Run at session start.
5. **Non-destructive** — never overwrites hand-written skill files. Uses markers to identify generated files.

## Commands

| Command | What it does |
|---------|-------------|
| `/skillgen` | Analyze codebase, generate skills, write to `.claude/skills/` |
| `/skillgen enrich` | Fetch community skills, evaluate fit against codebase, offer to install |
| `/skillgen save` | Alias for `/skillgen` — re-run analysis and overwrite generated skills |

`/skillgen diff` is explicitly deferred — re-running `/skillgen` is simpler and cheaper than computing diffs.

## Context Budget

**This skill consumes significant context.** Reading 15-20 source files means 3,000-10,000 lines of code loaded into context, plus the extraction and generation output.

Guidance embedded in the skill:
- Run `/skillgen` at the **start of a session** or in a **dedicated session**
- The generated `.claude/skills/*.md` files persist — future sessions get the benefit for ~200 lines of context (the skill files) instead of 10,000 (the source code)
- After generation, suggest the user start a new session for actual work if context is tight

## File Structure

One file:

```
.claude/commands/skillgen.md      ← the slash command
```

This file contains the complete prompt — detection logic, sampling strategy, extraction instructions, formatting rules, and write logic. Estimated ~400 lines.

## How `/skillgen` Works

### Phase 1: Detect Project Shape (~2 min context)

Use Glob to scan the project structure:

```
Glob("**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.go", "**/*.rs", "**/*.java")
```

Read manifest/config files to identify the stack:
- `pyproject.toml`, `package.json`, `tsconfig.json`, `go.mod`, `Cargo.toml`, `pom.xml`
- `ruff.toml`, `.prettierrc`, `.eslintrc.*`, `mypy.ini`, `.golangci.yml`

Output: language list, framework list, tool configuration values.

### Phase 2: Smart File Sampling (~5 min context)

Select 15-20 representative files using a multi-step process:

**Step 1: Filter junk**
Exclude files in: `node_modules/`, `vendor/`, `__pycache__/`, `dist/`, `build/`, `.git/`, `migrations/`, `generated/`, `*.min.js`, `*.bundle.*`

**Step 2: Classify files by role**
- Source files: business logic, utilities, models
- Test files: test_*, *.test.*, *_test.*
- Config files: pyproject.toml, ruff.toml, .prettierrc, etc.
- Entry points: main.py, index.ts, main.go, App.tsx

**Step 3: Sample diversely**
Pick from DIFFERENT directories to get architectural breadth:
- 1 entry point file
- 2-3 config/manifest files (read these fully — they're small)
- 3-4 source files from different directories (not the largest — the most *representative*)
- 2-3 test files from different test directories
- 1-2 files from each detected language (for multi-language projects)

**Anti-heuristics (things NOT to do):**
- Don't pick "largest files" — they're often auto-generated, migrations, or data dumps
- Don't read more than 200 lines of any single file — head is enough to see patterns
- Don't read more than 20 files total — diminishing returns

### Phase 3: Extract Conventions (~10 min context)

Claude reads the sampled files and extracts conventions across 8 categories. The skill prompt includes a **systematic checklist** to prevent skipping categories:

```
For EACH category, extract conventions with evidence. If a category has
no detectable patterns, state "No clear conventions detected" — do NOT
generate generic advice.

CHECKLIST (do not skip any):

□ NAMING CONVENTIONS
  - Function/method naming pattern (with 3+ examples from actual code)
  - Class/type naming pattern (with examples)
  - File naming pattern
  - Variable naming (constants, private, etc.)

□ ERROR HANDLING
  - Exception types used (which ones, where)
  - Try/catch patterns (what is caught, what is re-raised)
  - Custom error classes (if any)
  - Error propagation style

□ TESTING
  - Framework (pytest, jest, go test, etc.)
  - File organization (where tests live, naming)
  - Fixture/setup patterns
  - Assertion style
  - What IS tested vs what ISN'T

□ IMPORTS & DEPENDENCIES
  - Import style (absolute vs relative, grouping)
  - Key dependencies and how they're used
  - Barrel files / re-exports

□ DOCUMENTATION
  - Docstring/JSDoc format and coverage
  - Comment style and density
  - Module-level documentation

□ ARCHITECTURE
  - Directory structure and what goes where
  - Layer separation (routes/controllers, services, models)
  - Key patterns (dependency injection, middleware, etc.)

□ CODE STYLE
  - Formatter/linter configuration (from config files read in Phase 1)
  - Quote style, semicolons, trailing commas
  - Type annotation coverage
  - Line length

□ LOGGING & OBSERVABILITY
  - Logging library and initialization pattern
  - Log levels used
  - Structured vs unstructured logging
```

### Phase 4: Write Skill Files

Write one `.md` file per category (that has detected patterns) to `.claude/skills/`.

**Overwrite rules:**
- Read existing `.claude/skills/` directory
- Files with `<!-- Generated by skillgen -->` marker: overwrite
- Files WITHOUT the marker: never touch (hand-written)
- New categories not previously generated: create

**File format:**

```markdown
<!-- Generated by skillgen | Do not edit — re-run /skillgen to update -->

# Naming Conventions

## Function Naming
- Functions follow **verb_noun** pattern: `get_user`, `create_order`, `validate_input`
- Private helpers use `_underscore` prefix: `_parse_config`, `_build_query`

## Class Naming
- PascalCase for all classes: `UserService`, `CodePattern`, `SkillDefinition`
- Dataclasses use noun form: `ProjectInfo`, `AnalysisResult`

## File Naming
- snake_case.py matching module purpose: `analyzer.py`, `ts_parser.py`
- Test files: `test_<module>.py` in `tests/` directory
```

### Phase 5: Summary

After writing, print:
```
Generated 7 skill files in .claude/skills/:
  naming-conventions.md    (24 lines)
  error-handling.md        (31 lines)
  testing.md               (28 lines)
  imports.md               (18 lines)
  documentation.md         (15 lines)
  architecture.md          (22 lines)
  code-style.md            (35 lines)

Skipped: logging (no clear patterns detected)

These conventions are now active for this session and all future sessions.
Commit .claude/skills/ to share with your team.
```

## How `/skillgen enrich` Works

### Step 1: Fetch Community Index

Use Bash tool to fetch the index:
```bash
curl -s https://raw.githubusercontent.com/skillgen/skill-index/main/index.json
```

If curl fails, report gracefully and skip enrichment. No hard dependency on network access.

### Step 2: Match and Filter

From the index, find skills matching:
- Detected language(s) — required
- Detected framework(s) — if the skill specifies one
- Categories not already covered by local analysis

### Step 3: Evaluate Fit

For each matched skill, Claude reads:
- The community skill content (fetched via curl)
- The relevant local files from the project

Then Claude evaluates:
- **Aligns:** "This skill recommends fixture scoping, which matches your conftest.py hierarchy."
- **Conflicts:** "This skill recommends class-based views, but your project uses function-based views exclusively."
- **Fills gap:** "Your project has no structured logging patterns. This skill covers zerolog setup."

### Step 4: Interactive Approval

Present findings to the user:
```
Found 3 community skills for Python + FastAPI:

1. FastAPI Conventions (architecture, error-handling)
   ✓ Aligns with your router structure
   ⚠ Recommends BackgroundTasks — you don't use these yet

2. Pytest Patterns (testing)
   ✓ Aligns with your fixture hierarchy
   + Adds parametrize patterns you don't use yet

3. SQLAlchemy Patterns (architecture)
   ✓ Relevant — you use SQLAlchemy
   ⚠ Recommends async sessions — you use sync

Which would you like to install? (1,2,3 / all / none)
```

### Step 5: Write Selected Skills

Write to `.claude/skills/community/` with source headers:
```markdown
<!-- Source: skillgen/skill-index | Community skill, not derived from your code -->
```

## Non-Determinism Acknowledgment

This skill produces different output on different runs. This is a feature (richer, contextual output) and a tradeoff (inconsistent between team members).

**For teams that need consistency:** use the standalone CLI (`skillgen .`), which is deterministic. Commit the CLI-generated files.

**For individual developers:** `/skillgen` produces better output because Claude understands intent, not just syntax. Run it when you want fresh analysis.

## What This Does NOT Do

- No regex or tree-sitter — Claude reads code directly
- No Python dependencies — pure markdown skill file
- No `.cursor/rules/` or `AGENTS.md` — those are CLI-only (multi-tool support)
- No automatic/background runs — user explicitly invokes `/skillgen`
- No `/skillgen diff` — re-run `/skillgen` instead
- No caching — each run is fresh analysis

## Relationship to CLI

| Aspect | CLI (`skillgen .`) | Plugin (`/skillgen`) |
|--------|-------------------|---------------------|
| Analysis engine | regex + tree-sitter | Claude's understanding |
| Output quality | Good (statistical) | Better (semantic) |
| Determinism | Yes — same input, same output | No — varies per run |
| Output formats | .claude/ + .cursor/ + AGENTS.md | .claude/ only |
| Team consistency | High (commit generated files) | Lower (per-user) |
| CI/CD | Works in pipelines | N/A |
| Dependencies | Python 3.11+, pip install | None (just the .md file) |
| Context cost | Zero (runs out of process) | 3,000-10,000 lines per run |
| Speed | <1 second | 30-60 seconds |
| Best for | Teams, CI, multi-tool | Individual developer |
