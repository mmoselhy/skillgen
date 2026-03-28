# Enrich v2: Multi-Source Community Skills with Trust Tiers

**Date:** 2026-03-28
**Status:** Approved
**Supersedes:** 2026-03-27-online-skill-enrichment-design.md (v1 — single hand-written index)

## Problem

The v1 enrich system uses a hand-written `index.json` with 15 manually authored skill files. This doesn't scale — the real-world ecosystem already has hundreds of quality convention files across trusted sources:

- **anthropics/skills** — 17 official agent skills with YAML frontmatter
- **anthropics/claude-code/plugins** — 13 official plugin examples
- **PatrickJS/awesome-cursorrules** — 179+ cursor rules (38.7k stars)
- **github/awesome-copilot** — 60+ copilot instructions (official GitHub)
- **josix/awesome-claude-md** — 100+ CLAUDE.md references
- **VoltAgent/awesome-claude-code-subagents** — 127+ subagents

The enrich command should tap into these real sources instead of maintaining a parallel, hand-written collection.

## Solution Overview

A **build pipeline** in the `mmoselhy/skill-index` repo crawls trusted sources daily via GitHub Actions, runs format-specific adapters to extract metadata, and produces a single `index.json`. The skillgen CLI fetches this one index at runtime — same flow as v1, but the index is auto-generated and richer.

```
  Trusted Sources                    skill-index repo                    skillgen CLI
  ┌──────────────┐                  ┌──────────────────┐               ┌─────────────┐
  │anthropics/   │─┐               │                  │               │             │
  │  skills      │ │  daily cron   │  adapters/*.py   │  index.json   │  --enrich   │
  │              │ ├──────────────▶│  build_index.py  │──────────────▶│  --trust    │
  │awesome-      │ │               │                  │  content_url  │  --apply    │
  │  cursorrules │─┤               │  sources.json    │──────────────▶│  --pick     │
  │              │ │               │                  │  (per skill)  │             │
  │awesome-      │─┘               └──────────────────┘               └─────────────┘
  │  copilot     │
  └──────────────┘
```

### Key Design Decisions

1. **Adapter per source** — each trusted repo gets a specific adapter that understands its format. No auto-detection magic.
2. **Shipped defaults + remote registry** — `sources.json` lives in the skill-index repo. skillgen ships a bundled index snapshot; remote index is fetched and cached at runtime.
3. **Normalize metadata, keep content intact** — consistent headers (trust, source, categories) but original content body preserved as-is.
4. **Pre-built index, content fetched on demand** — one index fetch for matching (~1 request), then individual content fetches only for skills the user installs.

## Index Schema v2

```json
{
  "version": 2,
  "updated": "2026-03-28T04:30:00Z",
  "sources_crawled": ["anthropics/skills", "PatrickJS/awesome-cursorrules", "github/awesome-copilot"],
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
      "tags": ["frontend", "design", "css", "html"],
      "updated_at": "2026-03-15"
    }
  ]
}
```

### Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique slug: `{source-prefix}-{skill-slug}` |
| `name` | string | yes | Human-readable display name |
| `language` | string | yes | `python`, `typescript`, `javascript`, `go`, `rust`, `java`, `any` |
| `framework` | string\|null | yes | Framework name (lowercase) or null for language-general skills |
| `categories` | string[] | yes | skillgen category slugs: `naming-conventions`, `error-handling`, `testing`, `imports-and-dependencies`, `documentation`, `architecture`, `code-style`, `logging-and-observability` |
| `description` | string | yes | One-line summary |
| `source_repo` | string | yes | GitHub `owner/repo` |
| `source_path` | string | yes | Path within the source repo |
| `content_url` | string | yes | Direct raw URL to fetch content |
| `trust` | string | yes | `official`, `community`, or `contributed` |
| `format` | string | yes | `skill-md`, `cursorrules`, `copilot-instructions`, `claude-md`, `markdown` |
| `tags` | string[] | no | Freeform tags for search |
| `updated_at` | string | no | ISO date of last source modification |

### Backward Compatibility

- `version: 2` lets the client distinguish v1 vs v2
- v1 clients ignore unknown fields — no breakage
- v2 clients handle missing new fields with defaults: `trust="contributed"`, `format="markdown"`, `content_url=""` (falls back to `BASE_URL + path`)

## Trust Tiers

| Tier | Label | Sources | Criteria |
|---|---|---|---|
| 1 | `official` | anthropics/skills, anthropics/claude-code/plugins, github/awesome-copilot | Maintained by platform vendors |
| 2 | `community` | PatrickJS/awesome-cursorrules, josix/awesome-claude-md, VoltAgent/awesome-claude-code-subagents | 1k+ stars, active maintenance |
| 3 | `contributed` | User-submitted via PR to skill-index repo | Reviewed before merge |

Trust tier determines:
- **Display order** — official first, then community, then contributed
- **Default filter** — `--trust all` by default; user can restrict with `--trust official`
- **Visual indicator** — shown in the enrich preview table

## Adapters

Each adapter implements the same protocol:

```python
@dataclass
class RawSkill:
    """A skill extracted from a source before normalization."""
    name: str
    content: str
    source_path: str
    language: str          # detected or inferred
    framework: str | None
    categories: list[str]
    description: str
    tags: list[str]
    updated_at: str        # from git or file metadata

class Adapter(Protocol):
    repo: str              # "anthropics/skills"
    trust: str             # "official"

    def crawl(self) -> list[RawSkill]:
        """Fetch repo tree, read files, return raw skills."""
        ...
```

### Adapter Implementations

| Adapter | Source Repo | Format | Classification Strategy |
|---|---|---|---|
| `anthropic_skills` | anthropics/skills | SKILL.md + YAML frontmatter | Parse frontmatter for name, description. Map `allowed-tools` and content to categories. Language from content analysis. |
| `anthropic_plugins` | anthropics/claude-code/plugins | plugin.json + dirs | Parse JSON manifests. Extract skill descriptions from nested `skills/*/SKILL.md`. |
| `copilot_instructions` | github/awesome-copilot | Markdown | Read categorized markdown files. Infer language/framework from directory names and file content. |
| `cursorrules` | PatrickJS/awesome-cursorrules | Plain text .cursorrules | Read `.cursorrules` files. Parse folder name for language/framework (e.g., `nextjs-cursorrules-prompt-file` -> typescript, next). Classify categories from content keywords. |
| `claude_md_index` | josix/awesome-claude-md | Curated index | Follow links to real repos. Fetch CLAUDE.md content. Classify by tech stack from repo metadata. |
| `subagents` | VoltAgent/awesome-claude-code-subagents | Markdown | Read agent markdown files. Classify by category from README structure. |

### Category Classification

Adapters that handle unstructured content (cursorrules, copilot instructions) need to classify into skillgen's 8 categories. Strategy:

1. **Keyword matching** — scan content for category-indicative terms:
   - `naming`, `convention`, `case` → `naming-conventions`
   - `error`, `exception`, `try`, `catch` → `error-handling`
   - `test`, `spec`, `assert`, `mock` → `testing`
   - `import`, `require`, `dependency` → `imports-and-dependencies`
   - `doc`, `comment`, `jsdoc`, `docstring` → `documentation`
   - `architect`, `structure`, `layout`, `pattern` → `architecture`
   - `format`, `lint`, `style`, `indent` → `code-style`
   - `log`, `trace`, `metric`, `monitor` → `logging-and-observability`

2. **Multi-category assignment** — a cursorrule file typically covers multiple categories. Assign all that match above a threshold.

3. **Fallback** — if no category matches, assign `["architecture", "code-style"]` as the broadest defaults.

### Language/Framework Detection from Folder Names

For `awesome-cursorrules`, folder names follow `{tech}-cursorrules-prompt-file`:

```python
FOLDER_MAP = {
    "nextjs": ("typescript", "next"),
    "react": ("typescript", "react"),
    "python": ("python", None),
    "fastapi": ("python", "fastapi"),
    "django": ("python", "django"),
    "go": ("go", None),
    "rust": ("rust", None),
    "angular": ("typescript", "angular"),
    "express": ("javascript", "express"),
    # ... ~30 more mappings
}
```

## Build Pipeline

### Repo Structure

```
skill-index/
├── index.json                  # OUTPUT: auto-generated, committed by CI
├── sources.json                # registry of trusted sources + adapter mapping
├── adapters/
│   ├── __init__.py
│   ├── base.py                 # Adapter protocol, RawSkill dataclass
│   ├── anthropic_skills.py
│   ├── anthropic_plugins.py
│   ├── copilot_instructions.py
│   ├── cursorrules.py
│   ├── claude_md_index.py
│   └── subagents.py
├── build_index.py              # main: load sources → run adapters → dedupe → write index.json
├── contributed/                # manually submitted skills (trust: contributed)
│   └── *.md
├── tests/
│   └── test_adapters.py
├── .github/
│   └── workflows/
│       └── rebuild-index.yml
├── requirements.txt
└── README.md
```

### sources.json

```json
{
  "sources": [
    {"repo": "anthropics/skills", "adapter": "anthropic_skills", "trust": "official", "enabled": true},
    {"repo": "anthropics/claude-code", "adapter": "anthropic_plugins", "trust": "official", "enabled": true, "path_prefix": "plugins"},
    {"repo": "github/awesome-copilot", "adapter": "copilot_instructions", "trust": "official", "enabled": true},
    {"repo": "PatrickJS/awesome-cursorrules", "adapter": "cursorrules", "trust": "community", "enabled": true},
    {"repo": "josix/awesome-claude-md", "adapter": "claude_md_index", "trust": "community", "enabled": true},
    {"repo": "VoltAgent/awesome-claude-code-subagents", "adapter": "subagents", "trust": "community", "enabled": true}
  ]
}
```

### build_index.py Behavior

1. Load `sources.json`
2. For each enabled source: instantiate adapter, call `crawl()`
3. Deduplicate by `language + framework + name` tuple (same skill from different sources → keep highest trust tier, break ties by source order in `sources.json`)
4. Assign `id` as `{source-prefix}-{slug}` (e.g., `anthropic-frontend-design`, `cursorrules-nextjs`)
5. Construct `content_url` from `source_repo` + `source_path`
6. Add `contributed/*.md` entries with `trust: "contributed"`
7. Write `index.json`
8. Print stats: `Built index: 312 skills from 6 sources (47 official, 203 community, 62 contributed)`

### CI Workflow

```yaml
name: Rebuild Index
on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python build_index.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - name: Commit if changed
        run: |
          git diff --quiet index.json && exit 0
          git config user.name "skill-index-bot"
          git config user.email "bot@skillgen.dev"
          git add index.json
          git commit -m "chore: rebuild index ($(date -u +%Y-%m-%d))"
          git push
```

### Error Handling

- Single adapter failure → log warning, skip that source, continue. The index is rebuilt from all other sources.
- GitHub API rate limit → use `GITHUB_TOKEN` for 5000 req/hour. If exhausted, skip remaining sources, use previous results.
- Content fetch failure → skip that skill entry, don't include in index.

## Client Changes (skillgen package)

### enricher.py

**Minimal changes:**

1. `IndexEntry` dataclass gains optional v2 fields with defaults
2. `_parse_index` handles both v1 and v2 (missing fields get defaults)
3. `_match_entries` gains optional `trust_filter` parameter
4. `_fetch_skill_content` uses `entry.content_url` directly when available, falls back to `BASE_URL + path`
5. `_format_community_claude` includes trust and source in header comment

### models.py

`IndexEntry` grows:

```python
@dataclass
class IndexEntry:
    id: str
    name: str
    language: str
    framework: str | None
    categories: list[str]
    path: str
    description: str
    # v2 fields
    source_repo: str = ""
    content_url: str = ""
    trust: str = "contributed"
    format: str = "markdown"
    tags: list[str] = field(default_factory=list)
    updated_at: str = ""
```

### cli.py

New `--trust` flag:

```python
trust: str | None = typer.Option(
    None,
    "--trust",
    help="Filter by trust tier: official, community, contributed, or all. Default: all.",
)
```

Wired into enrich flow: passed to `_match_entries(entries, conventions, trust_filter=trust_set)`.

### renderer.py

Enrich preview table gains Trust and Source columns:

```
$ skillgen . --enrich

Found 23 community skills for Python:

  #  Trust       Skill                    Categories         Source
  1  official    Frontend Design          architecture       anthropics/skills
  2  official    Code Review              code-style         anthropics/claude-code
  3  community   Python Pytest Rules      testing            PatrickJS/awesome-cursorrules
  4  community   FastAPI Conventions      architecture       PatrickJS/awesome-cursorrules
  5  contributed Structlog Logging        logging            mmoselhy/skill-index

  Skipped (already covered locally): naming-conventions, imports-and-dependencies

  To install:  skillgen . --enrich --apply
  To filter:   skillgen . --enrich --trust official
  To pick:     skillgen . --enrich --apply --pick 1,3
```

### Installed File Format

```markdown
<!-- Community skill: Frontend Design (id: anthropic-frontend-design) -->
<!-- Source: anthropics/skills | Trust: official -->

{original content preserved as-is}
```

## `/skillgen enrich` Skill Changes

The Claude Code slash command workflow updates:

1. **Step 2 (Fetch):** Same URL, parses v2 fields
2. **Step 5 (Present):** Shows trust tier and source repo alongside the aligns/conflicts/fills-gap evaluation
3. **Step 6 (Install):** Updated header with trust and source
4. **`enrich.md` reference:** Schema docs updated to show v2 fields

The evaluation logic (read local files, compare, assign verdict) is unchanged — this remains the skill's unique value over the CLI.

## Migration Path

1. **Phase 1:** Build the adapter pipeline in `skill-index` repo. Generate v2 `index.json`. Existing hand-written skills move to `contributed/`.
2. **Phase 2:** Update `skillgen` client to handle v2 index. Add `--trust` flag. Update renderer.
3. **Phase 3:** Update `/skillgen enrich` skill to display trust/source.

Phases 1 and 2 are independent — the client handles both v1 and v2 indexes, so they can ship in any order.

## Out of Scope

- **Custom source URLs** (`--source <repo>`) — future enhancement, not in this version
- **Skill versioning/pinning** — skills are always latest from source
- **Skill ratings/reviews** — no community feedback mechanism
- **Private/enterprise indexes** — only public GitHub repos
- **Transitive skill dependencies** — skills are independent units
