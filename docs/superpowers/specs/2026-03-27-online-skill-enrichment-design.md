# Online Skill Enrichment (`--enrich`)

**Date:** 2026-03-27
**Status:** Approved
**Author:** brainstorming session

---

## Summary

After local code analysis, skillgen optionally fetches community-curated skills from a GitHub-hosted index that match the detected languages and frameworks. Online skills fill gaps only — categories where local analysis produced no results. Users preview available skills first, then explicitly apply the ones they want.

## Motivation

Local code analysis detects what your codebase already does. But new projects, projects without tests, or projects adopting a new framework have gaps — patterns that don't exist in code yet. Community-curated skills fill those gaps with vetted best practices for your specific stack.

## Design Principles

1. **Local-first** — `--enrich` is opt-in. Default behavior is fully offline.
2. **Evidence over opinion** — local analysis always takes priority. Online skills never override detected patterns.
3. **User reviews before install** — `--enrich` previews, `--enrich --apply` writes files. No surprise writes.
4. **Zero infrastructure** — index is a JSON file on GitHub. No API server, no database.

## Architecture

```
  DETECT → ANALYZE → SYNTHESIZE → GENERATE → WRITE
                                      │
                                  [ENRICH]  (if --enrich)
                                      │
                                      ▼
                              skill-index (GitHub)
                              ├── index.json
                              └── skills/**/*.md
```

### Pipeline Integration

The enricher runs after synthesis and before generation:

1. Local pipeline runs as normal (detect → analyze → synthesize)
2. If `--enrich` is set, enricher fetches index and matches skills
3. If `--apply` is also set, matched skills are downloaded and written to disk
4. If only `--enrich` (no `--apply`), matched skills are previewed in the terminal
5. Local generation proceeds independently — enriched skills are separate files

## New Module: `skillgen/enricher.py`

### Responsibilities

1. Fetch `index.json` from GitHub (with 24h cache)
2. Match entries against detected languages + frameworks
3. Filter out categories already covered by local synthesis
4. Preview matched skills in terminal
5. Download and write selected skills when `--apply` is set

### Public API

```python
@dataclass
class IndexEntry:
    """A single skill entry from the online index."""
    id: str
    name: str
    language: str
    framework: str | None
    categories: list[str]
    path: str
    description: str

@dataclass
class EnrichmentResult:
    """Result of the enrichment search."""
    matched: list[IndexEntry]       # skills that match this project
    skipped_categories: list[str]   # categories already covered locally
    errors: list[str]               # any fetch/parse errors


def search(conventions: ProjectConventions, cache_dir: Path | None = None) -> EnrichmentResult:
    """Fetch index and find matching community skills. No files written."""

def apply(
    entries: list[IndexEntry],
    target_dir: Path,
    output_format: OutputFormat,
    pick: list[int] | None = None,
    cache_dir: Path | None = None,
) -> list[WrittenFile]:
    """Download selected skills and write to disk."""
```

## Index Format

Hosted at: `https://raw.githubusercontent.com/skillgen/skill-index/main/index.json`

Repository structure:
```
skill-index/
├── index.json
└── skills/
    ├── python/
    │   ├── fastapi.md
    │   ├── django.md
    │   ├── flask.md
    │   └── pytest.md
    ├── typescript/
    │   ├── nextjs.md
    │   ├── react.md
    │   └── vitest.md
    ├── go/
    │   ├── gin.md
    │   └── cobra.md
    └── rust/
        ├── actix.md
        └── tokio.md
```

### `index.json` schema

```json
{
  "version": 1,
  "updated": "2026-03-27",
  "skills": [
    {
      "id": "python-fastapi",
      "name": "FastAPI Conventions",
      "language": "python",
      "framework": "FastAPI",
      "categories": ["error-handling", "testing", "architecture"],
      "path": "skills/python/fastapi.md",
      "description": "API error handling, dependency injection, test client patterns"
    },
    {
      "id": "python-pytest",
      "name": "Pytest Best Practices",
      "language": "python",
      "framework": null,
      "categories": ["testing"],
      "path": "skills/python/pytest.md",
      "description": "Fixtures, parametrize, conftest organization, mocking patterns"
    }
  ]
}
```

### Matching Logic

1. **Language match (required):** `entry.language` must be one of the detected languages
2. **Framework match (optional):** if `entry.framework` is set, it must be one of the detected frameworks. If `null`, the skill applies to all projects of that language.
3. **Category filter:** skip entries whose categories are ALL already covered by local synthesis (i.e., `ProjectConventions.categories` has non-empty `CategorySummary` for every category the skill covers)

## CLI Flags

### New flags

| Flag | Type | Description |
|------|------|-------------|
| `--enrich` | bool | Search online index for community skills matching this project |
| `--apply` | bool | Download and write matched community skills (requires `--enrich`) |
| `--pick` | str | Comma-separated indices to cherry-pick specific skills (e.g., `--pick 1,3`) |
| `--no-cache` | bool | Force re-fetch of index and skills, ignoring cache |

### Flag Combinations

| Command | Behavior |
|---------|----------|
| `skillgen .` | Local only, no network |
| `skillgen . --enrich` | Local generation + preview community skills in terminal |
| `skillgen . --enrich --apply` | Local generation + download ALL matched community skills |
| `skillgen . --enrich --apply --pick 1,3` | Local generation + download only selected skills |
| `skillgen . --enrich --dry-run` | Preview community skills without writing any files |

### Validation

- `--apply` without `--enrich` → error: "Use --enrich --apply together"
- `--pick` without `--apply` → error: "Use --pick with --enrich --apply"
- `--pick 5` when only 3 matched → error: "Only 3 skills matched. Valid range: 1-3"

## Terminal Output

### Preview mode (`--enrich`)

```
  Found 4 community skills for Python + FastAPI:

  ┌───┬────────────────────────┬───────────────┬─────────────┐
  │ # │ Skill                  │ Category      │ Source      │
  ├───┼────────────────────────┼───────────────┼─────────────┤
  │ 1 │ FastAPI Conventions    │ architecture  │ skill-index │
  │ 2 │ FastAPI Testing        │ testing       │ skill-index │
  │ 3 │ Pytest Best Practices  │ testing       │ skill-index │
  │ 4 │ SQLAlchemy Patterns    │ architecture  │ skill-index │
  └───┴────────────────────────┴───────────────┴─────────────┘

  Skipped (already covered by local analysis):
    naming-conventions, code-style, imports-and-dependencies

  To install: skillgen . --enrich --apply
  To pick:    skillgen . --enrich --apply --pick 1,2
```

### Apply mode (`--enrich --apply`)

```
  Downloaded and installed 2 community skills:

  ┌──────────────────────────────────────────────┬────────┬───────┐
  │ File                                         │ Format │ Lines │
  ├──────────────────────────────────────────────┼────────┼───────┤
  │ .claude/skills/community/fastapi-testing.md  │ Claude │    45 │
  │ .cursor/rules/community/fastapi-testing.mdc  │ Cursor │    46 │
  │ .claude/skills/community/pytest-patterns.md  │ Claude │    38 │
  │ .cursor/rules/community/pytest-patterns.mdc  │ Cursor │    39 │
  └──────────────────────────────────────────────┴────────┴───────┘

  Done! 4 community skill files installed.
```

## File Output

Community skills are written to a `community/` subdirectory to keep them separate from locally-generated skills:

```
.claude/skills/
├── naming-conventions.md       # local (generated by skillgen)
├── code-style.md               # local
├── testing.md                  # local
└── community/
    ├── fastapi-testing.md      # online (from skill-index)
    └── pytest-patterns.md      # online

.cursor/rules/
├── naming-conventions.mdc      # local
├── code-style.mdc              # local
└── community/
    ├── fastapi-testing.mdc     # online
    └── pytest-patterns.mdc     # online
```

### Community skill file format

Each downloaded skill gets a header marking its origin:

```markdown
<!-- Source: skillgen/skill-index | Community skill, not derived from your code -->
<!-- Skill: python-fastapi (v1) | Last fetched: 2026-03-27 -->

---
name: fastapi-testing
description: Community best practices for testing FastAPI applications.
---

# FastAPI Testing (Community)
...
```

## Caching

| Item | Location | TTL |
|------|----------|-----|
| `index.json` | `~/.cache/skillgen/index.json` | 24 hours |
| Individual skills | `~/.cache/skillgen/skills/<id>.md` | 24 hours |

- `--no-cache` forces re-fetch
- Cache directory is created on first use
- Stale cache entries are used as fallback if network fails

## Error Handling

| Failure | Behavior | User sees |
|---------|----------|-----------|
| No network / DNS failure | Skip enrichment | Warning under `--verbose`, nothing otherwise |
| Index fetch timeout (10s) | Skip enrichment | "Could not reach skill index (timeout)" |
| Index JSON malformed | Skip enrichment | "Skill index is malformed, skipping" |
| Skill file 404 | Skip that skill | "Skill 'python-fastapi' not found, skipping" |
| All matched skills filtered | Normal exit | "Local analysis covers all categories" |
| `--apply` with no matches | Normal exit | "No community skills to install" |

All errors are non-fatal. Local generation always completes regardless of enrichment failures.

## Network Details

- Uses `urllib.request` from stdlib (no new dependencies)
- User-Agent: `skillgen/{version}`
- Timeout: 10 seconds per request
- No authentication required (public GitHub raw content)
- Base URL: `https://raw.githubusercontent.com/skillgen/skill-index/main/`

## Changes to Existing Modules

| Module | Change |
|--------|--------|
| `models.py` | Add `EnrichedSkill` dataclass, add `enriched_skills` field to `ProjectConventions` |
| `cli.py` | Add `--enrich`, `--apply`, `--pick`, `--no-cache` flags. Call enricher between synthesize and generate. |
| `renderer.py` | Add `render_enrich_preview()` and `render_enrich_result()` functions |
| `writer.py` | Add `_write_community_skills()` to write into `community/` subdirectory |
| `generator.py` | No changes — enriched skills bypass the generator entirely |
| `enricher.py` | New module (entire enrichment logic) |

## Testing Strategy

| Test | Type | What it covers |
|------|------|---------------|
| Index parsing | Unit | Parse valid index.json, malformed JSON, missing fields |
| Matching logic | Unit | Language match, framework match, category filtering |
| Cache read/write | Unit | Write cache, read fresh cache, expire stale cache |
| Network failure | Unit | Mock urllib to simulate timeout, 404, DNS failure |
| File writing | Integration | Community skills written to correct subdirectory |
| `--pick` validation | Unit | Valid picks, out-of-range picks, no picks |
| End-to-end | Integration | Full pipeline with `--enrich --apply` against mock server |

All network tests must use mocking — no real HTTP calls in the test suite.

## Out of Scope

- Scraping arbitrary GitHub repos for skills
- User-submitted skills (no upload mechanism)
- Rating or voting on skills
- Versioned skill updates (skills are fetched as-is)
- Authentication or private index support
- AGENTS.md enrichment (community skills go to .claude/skills/ and .cursor/rules/ only)

## Dependencies

No new runtime dependencies. Uses:
- `urllib.request` (stdlib) for HTTP
- `json` (stdlib) for parsing
- `pathlib` (stdlib) for cache paths

## Future Considerations

- If adoption grows, the index could move to a dedicated API with search, versioning, and ratings
- A `skillgen contribute` command could help users submit skills back to the index
- Private/enterprise index URLs could be supported via `--index-url` flag
