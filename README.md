# skillgen

**Analyze any codebase and auto-generate AI agent skill files for Claude Code, Cursor, and other AI tools.**

Stop hand-writing `.claude/skills/` and `.cursor/rules/` files. Run one command, and every AI assistant on your team speaks your project's language — naming conventions, test patterns, error handling, architecture, and more. Every line in the output is backed by evidence from your actual codebase.

```
$ skillgen . --dry-run --format claude

 Scanning files and detecting languages...  0:00
 Analyzing patterns...                      0:00
 Synthesizing conventions...                0:00
 Generating skills...                       0:00

--- naming-conventions (dry run, not written) ---
# Naming Conventions
<!-- Confidence: MEDIUM | Based on 14 files, 22 patterns -->

## Function Naming
- **82% Functions use snake_case** (14/17 files)
  - Examples: `analyze_project (analyzer.py)`, `detect_project (detector.py)`

## Class Naming
- **41% Classes/types use PascalCase** (7/17 files)
  - Examples: `Language (models.py)`, `PatternCategory (models.py)`

--- code-style (dry run, not written) ---
# Code Style
<!-- Confidence: MEDIUM | Based on 15 files, 53 patterns -->

## Line Length
- **64% Lines generally within 120 characters** (11/17 files)
  - Configured in ruff: line-length = 100

## Quote Style
- **88% Prefers double quotes** (15/17 files)

## Type Hints
- **88% Uses type hints** (15/17 files)

## Formatters & Linters
- ruff -- line-length: 100, select: E, F, W, I, N, UP, B, SIM, RUF
- mypy -- strict mode, python_version: 3.11

Done! 17 file(s) would be generated.
```

## Two Ways to Use skillgen

### 1. CLI Tool (teams, CI, multi-format)

```bash
pip install skillgen-ai
skillgen ./my-project
```

Generates `.claude/skills/`, `.cursor/rules/`, and `AGENTS.md`. Deterministic output, works offline, runs in CI. Best for teams committing shared conventions.

### 2. Claude Code Plugin (individual devs)

Type `/skillgen` inside Claude Code. No installation needed — it's a slash command that ships with this repo.

Claude reads your code directly and generates skill files using its own understanding. If the CLI is installed, `/skillgen` uses **hybrid mode** — CLI statistics + Claude's semantic analysis — for the best of both worlds.

| Aspect | CLI | `/skillgen` Plugin |
|--------|-----|-------------------|
| Analysis | Regex + tree-sitter | Claude reads code |
| Output | Statistical ("82% snake_case") | Semantic ("verb_noun pattern: get_user") |
| Formats | .claude/ + .cursor/ + AGENTS.md | .claude/ only |
| Context cost | Zero (out of process) | ~1,700 lines (hybrid) or ~10,000 (standalone) |
| Deterministic | Yes | No (richer but varies) |
| Speed | <1 second | 5-15 seconds |

## Installation

```bash
pip install skillgen-ai
```

Optional extras:

```bash
pip install skillgen-ai[tree-sitter]  # AST-based analysis (more accurate)
pip install skillgen-ai[llm]          # LLM-enhanced output (requires API key)
```

## Quick Start

### CLI

```bash
# Generate skill files for your project
skillgen ./my-project

# Commit so your whole team benefits
git add .claude/ .cursor/ AGENTS.md && git commit -m "Add AI agent skill files"
```

### Claude Code Plugin

```
/skillgen              Analyze codebase, write .claude/skills/*.md
/skillgen enrich       Find community skills for your stack
/skillgen save         Same as /skillgen (alias for clarity)
```

## CLI Reference

```
skillgen <path> [flags]

Arguments:
  <path>    Path to the codebase to analyze. Defaults to "." if omitted.

Output Flags:
  --format, -f <claude|cursor|all>
                Target AI tool format. Default: all.
                  claude  - .claude/skills/*.md only
                  cursor  - .cursor/rules/*.mdc only
                  all     - All formats plus AGENTS.md

  --diff        Show what the AI agent learns vs. a blank-slate agent.
  --dry-run     Preview generated files without writing to disk.
  --json        Output full analysis as structured JSON and exit.
  --verbose, -v Show detailed analysis steps and stats.
  --quiet, -q   Suppress all output except errors.

Analysis Flags:
  --no-tree-sitter
                Disable tree-sitter AST parsing, use regex fallback.

  --llm         Use LLM (Claude or GPT-4o) to enhance output.
                Requires ANTHROPIC_API_KEY or OPENAI_API_KEY.

  --llm-provider <anthropic|openai>
                Select LLM provider. Auto-detected by default.

Community Skills:
  --enrich      Search online index for community skills matching
                your project. Preview only — does not write files.

  --enrich --apply
                Download and install matched community skills.

  --enrich --apply --pick 1,3
                Cherry-pick specific skills by number.

  --no-cache    Force re-fetch of online skill index.

Other:
  --version     Print version and exit.
  --help        Print help and exit.
```

### Examples

```bash
# Analyze current directory, generate all formats
skillgen .

# Preview what would be generated
skillgen ./my-project --dry-run

# Claude Code skills only
skillgen ./my-project --format claude

# Cursor rules only
skillgen ./my-project --format cursor

# See what the AI agent learns vs blank-slate
skillgen ./my-project --diff

# Export as JSON for custom tooling
skillgen ./my-project --json > conventions.json

# Find community skills for your FastAPI project
skillgen ./my-project --enrich

# Install the ones you want
skillgen ./my-project --enrich --apply --pick 1,2

# Use LLM for higher-quality output
ANTHROPIC_API_KEY=sk-... skillgen ./my-project --llm

# CI-friendly: quiet mode
skillgen ./my-project --quiet
```

## Output Format Examples

### Claude Code: `.claude/skills/code-style.md`

```markdown
<!-- Generated by skillgen v0.1.0. Do not edit manually. -->

---
name: code-style
description: Formatting, line length, quote style, linter/formatter usage.
---

# Code Style
<!-- Confidence: MEDIUM | Based on 15 files, 53 patterns -->

## Line Length
- **64% Lines generally within 120 characters** (11/17 files)
  - Configured in ruff: line-length = 100

## Quote Style
- **88% Prefers double quotes** (15/17 files)

## Type Hints
- **88% Uses type hints** (15/17 files)

## Formatters & Linters
- **ruff** -- line-length: 100, select: E, F, W, I, N, UP, B, SIM, RUF
- **mypy** -- python_version: 3.11, strict: true
```

### Cursor: `.cursor/rules/code-style.mdc`

Same content with Cursor-specific frontmatter (`globs`, `alwaysApply`).

### AGENTS.md

Single Markdown file at repo root with `<!-- skillgen:start -->` / `<!-- skillgen:end -->` markers. Preserves existing content outside the markers.

## How It Works

### CLI Pipeline

Five stages, entirely local and deterministic by default:

```
  path ──▶ DETECT ──▶ ANALYZE ──▶ SYNTHESIZE ──▶ GENERATE ──▶ WRITE
            │          │            │               │            │
         languages   patterns    conventions     skills       files
         frameworks  evidence    config values   confidence   .claude/
                     per-file    prevalence      meter        .cursor/
                                 stats                        AGENTS.md
```

1. **Detect** — Scan file tree, count extensions, read manifests, identify languages and frameworks
2. **Analyze** — Sample up to 50 files/language, extract patterns across 8 categories (regex or tree-sitter)
3. **Synthesize** — Deduplicate, compute prevalence stats, parse config files (ruff, prettier, mypy, eslint)
4. **Generate** — Render evidence-only skills with confidence meters. No generic advice.
5. **Write** — Atomic writes. Clean up orphaned files. Respect `--dry-run`.

### `/skillgen` Plugin Pipeline

When you type `/skillgen` in Claude Code:

```
  Phase 0: CLI installed?
    ├── YES (hybrid) ──▶ skillgen . --json ──▶ Read 5-8 files ──▶ Combine stats + semantics
    └── NO (standalone) ──▶ Read 15-20 files ──▶ Claude extracts everything
                                                        │
                                                        ▼
                                               Write .claude/skills/*.md
```

**Hybrid mode** (CLI installed): Uses CLI's deterministic stats as the backbone. Claude reads only 5-8 files for semantic enrichment — naming patterns, architectural intent, contextual guidance. Uses ~1,700 lines of context instead of ~10,000.

**Standalone mode** (CLI not installed): Claude reads 15-20 files and extracts everything from scratch. Richer than regex but uses more context.

## Community Skills (`--enrich`)

After local analysis, skillgen can search an online index for community-curated skills matching your language and framework:

```bash
$ skillgen ./my-fastapi-project --enrich

Found 3 community skills for Python + FastAPI:

  #  Skill                   Categories              Description
  1  FastAPI Conventions      architecture, errors    Router patterns, DI, HTTPException
  2  Pytest Best Practices    testing                 Fixtures, parametrize, conftest
  3  SQLAlchemy Patterns      architecture            Session management, eager loading

  Skipped (already covered locally): naming, code-style, imports

  To install: skillgen . --enrich --apply
  To pick:    skillgen . --enrich --apply --pick 1,2
```

Community skills are:
- Written to `.claude/skills/community/` (separate from locally-generated skills)
- Tagged with `<!-- Source: mmoselhy/skill-index -->` so you know the origin
- Only offered for categories NOT already covered by local analysis
- Fetched from a GitHub-hosted index with 24h local cache

Currently 15 community skills covering Python (FastAPI, Django, Flask, pytest, SQLAlchemy), TypeScript (Next.js, React, Vitest), JavaScript (Express), Go (Gin, Cobra, stdlib), Rust (Actix, Tokio), and Java (Spring).

## Supported Languages

| Language   | Extensions                          | Frameworks Auto-Detected                |
|------------|-------------------------------------|-----------------------------------------|
| Python     | `.py`, `.pyi`                       | Django, FastAPI, Flask                   |
| TypeScript | `.ts`, `.tsx`                       | Next.js, React, Angular, Vue            |
| JavaScript | `.js`, `.jsx`                       | Express, React, Vue                      |
| Java       | `.java`                             | Spring                                   |
| Go         | `.go`                               | Gin, Cobra                               |
| Rust       | `.rs`                               | Actix, Tokio                             |
| C++        | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.h` | —                                        |

## Config File Parsing

skillgen reads your actual tool configs and embeds settings in generated skills:

| Tool | Files Read | Settings Extracted |
|------|-----------|-------------------|
| ruff | `ruff.toml`, `pyproject.toml [tool.ruff]` | line-length, target-version, select, quote-style |
| Prettier | `.prettierrc`, `.prettierrc.json` | singleQuote, semi, tabWidth, printWidth |
| ESLint | `.eslintrc.json`, `.eslintrc.js` | Presence detected |
| mypy | `mypy.ini`, `pyproject.toml [tool.mypy]` | strict mode, python_version |
| golangci-lint | `.golangci.yml`, `.golangci.yaml` | Enabled linters |

## Tree-sitter (Optional)

```bash
pip install skillgen-ai[tree-sitter]
```

Installs AST grammars for all 7 languages. When available, skillgen automatically uses AST-based extraction:

- Eliminates false positives from strings/comments/docstrings
- Detects type annotations structurally
- Distinguishes methods vs top-level functions
- Finds decorators accurately
- Handles multi-line constructs

Per-language fallback: if Python grammar is installed but Go isn't, Python uses AST while Go uses regex. Disable with `--no-tree-sitter`.

## JSON Output

```bash
skillgen ./my-project --json | jq '.categories["code-style"].entries[].description'
```

Exports all conventions with prevalence stats, config values, evidence, and confidence scores. Useful for custom dashboards, CI checks, or feeding into other tools.

## LLM Enhancement

```bash
ANTHROPIC_API_KEY=sk-ant-... skillgen ./my-project --llm
```

Sends skill drafts to Claude or GPT-4o for enhancement. Falls back to local generation on failure. Optional: `pip install skillgen-ai[llm]`.

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for development setup, testing, code style, and PR guidelines.

## License

[MIT](LICENSE)
