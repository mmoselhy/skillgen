# `/skillgen` Hybrid Mode — CLI Stats + Claude Semantics

**Date:** 2026-03-27
**Status:** Approved
**Author:** brainstorming session

---

## Summary

Update the existing `/skillgen` Claude Code plugin (`.claude/skills/skillgen/SKILL.md`) to detect whether the `skillgen` CLI is installed and, if so, use its `--json` output as a statistical backbone. Claude then reads only 5-8 key files for semantic enrichment instead of 15-20. The result combines exact statistics from the CLI with semantic understanding from Claude — strictly better than either alone.

When the CLI is not installed, the plugin falls back to the current standalone mode (Phases 1-5 unchanged).

## Motivation

| Problem | Hybrid solution |
|---------|----------------|
| Claude can't count across 50 files accurately | CLI scans all 50 and reports exact percentages |
| CLI can't understand naming intent | Claude reads key files and adds "verb_noun pattern" |
| Plugin consumes ~10,000 lines of context | Hybrid uses ~1,700 lines (JSON + 5-8 files) |
| CLI doesn't know where new code should go | Claude reads architecture and infers guidance |
| Plugin might skip categories | CLI guarantees all 8 categories covered |

## Changes to SKILL.md

### New: Phase 0 — CLI Detection

Insert before the current Phase 1. This is the branching point:

```
Run: skillgen --version

If exit code 0 (CLI available):
  Print: "skillgen CLI detected. Using hybrid mode: CLI stats + Claude semantics."
  Run: skillgen . --json
  Parse the JSON. You now have:
    - project_info: languages, frameworks, file counts, manifests
    - categories: dict of 8 categories, each with entries containing
      prevalence, file_count, total_files, confidence, evidence, conflicts
    - config_settings: tool config values (ruff.line-length, prettier.singleQuote, etc.)
    - config_files_parsed: list of config files read
    - files_analyzed: exact count
  Skip Phase 1 entirely. Proceed to Phase 2 (Hybrid Sampling).

If command not found (CLI not available):
  Print: "skillgen CLI not installed. Using standalone mode."
  Print: "Tip: pip install skillgen for faster, more accurate analysis."
  Proceed to Phase 1 (current standalone detection).
```

### Modified: Phase 2 — Hybrid Sampling (when CLI available)

When CLI data is available, Claude only needs files for semantic understanding. Reduce from 15-20 files to 5-8:

- 1 entry point (main.py, index.ts, etc.) — first 150 lines
- 2-3 source files from different directories — first 200 lines each
  - Pick files the CLI flagged as having the most patterns (look at the JSON entries' evidence for filenames)
- 1-2 test files — first 200 lines each
- 1 model/type definition file — fully if <200 lines

Total context: ~1,000-1,500 lines of code + ~200 lines of JSON = ~1,700 lines.
Compare to standalone: ~5,000-10,000 lines.

The existing standalone Phase 2 (15-20 files) remains for when CLI is not available.

### Modified: Phase 3 — Hybrid Extraction (when CLI available)

Each category now has two data sources. The extraction prompt changes to combine them:

```
For each of the 8 categories, you have:
  1. CLI DATA: exact statistics from the JSON (prevalence percentages,
     file counts, config values, evidence strings, conflict annotations)
  2. YOUR READING: semantic understanding from the 5-8 files you read

COMBINE them following these rules:

- QUANTITATIVE claims come from CLI data:
  "**82% use snake_case** (14/17 files)"
  NOT "most functions use snake_case" (vague)

- SEMANTIC insight comes from your reading:
  "specifically the **verb_noun** pattern: `get_user`, `create_order`"
  NOT just listing the CLI's evidence strings

- CONFIG values come from CLI data verbatim:
  "**Configured in ruff:** line-length = 100, select = E, F, W, I, N"

- ARCHITECTURAL guidance comes from your reading:
  "New API endpoints go in `app/routers/` following the existing router pattern"

- CONFLICTS: if the CLI reported a conflict in the JSON, explain it
  using context from files you read:
  "82% snake_case, but `legacy/old_api.py` uses camelCase (historical)"

- DO NOT just reformat the CLI JSON into markdown. Add genuine semantic
  value from the files you read. If you can't add anything beyond what
  the CLI already says for a category, use the CLI data as-is.

- The 8-category checklist still applies. Process every category the
  CLI reported, plus check if your reading reveals anything the CLI missed.
```

The existing standalone Phase 3 (full extraction checklist) remains for when CLI is not available.

### Modified: Phase 5 — Summary

Add hybrid mode indicator:

```
/skillgen complete! (hybrid mode: CLI stats + Claude semantics)

Generated N skill files in .claude/skills/:
  ...

Powered by skillgen v0.1.0 (statistical analysis) + Claude (semantic enrichment).
```

### Unchanged

- Frontmatter (same metadata, same allowed-tools)
- Command router (same subcommand dispatch)
- Phase 4 write rules (same marker safety, same file format)
- Enrich subcommand (same — uses curl, not CLI)
- Standalone Phases 1-5 (preserved as fallback)

## Context Budget Comparison

| Mode | What's loaded | Context lines | Time |
|------|-------------|---------------|------|
| Standalone (CLI not installed) | 15-20 source files | ~10,000 | 30-60s |
| Hybrid (CLI installed) | JSON output + 5-8 files | ~1,700 | 5-15s |

## Output Quality Comparison

| Aspect | CLI alone | Standalone plugin | Hybrid plugin |
|--------|----------|------------------|---------------|
| Statistical accuracy | Exact | Approximate | **Exact** (from CLI) |
| Semantic richness | None | High | **High** (from Claude) |
| Config values | Parsed | Only if reads configs | **Parsed** (from CLI) |
| Category coverage | All 8 guaranteed | May miss some | **All 8 guaranteed** |
| Contextual guidance | None | Good | **Good** (from Claude) |
| Context cost | 0 | ~10,000 lines | **~1,700 lines** |

## Error Handling

| Failure | Behavior |
|---------|----------|
| `skillgen --version` fails | Fall back to standalone mode |
| `skillgen . --json` fails | Fall back to standalone mode |
| JSON output is malformed | Fall back to standalone mode |
| JSON output is empty (no categories) | Fall back to standalone mode |
| CLI produces JSON but a specific category is empty | Use CLI data for categories that have data, Claude-only for empty ones |

All fallbacks are silent — just print "Using standalone mode" and proceed.

## File Changes

Only one file changes: `.claude/skills/skillgen/SKILL.md`

The changes are:
1. Insert Phase 0 (CLI detection) before Phase 1
2. Add hybrid variant of Phase 2 (5-8 files) alongside existing standalone variant
3. Add hybrid variant of Phase 3 (combine CLI + reading) alongside existing standalone variant
4. Update Phase 5 summary for hybrid mode indicator
5. Update context budget warning to mention both modes
