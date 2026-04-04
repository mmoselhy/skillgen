# skillgen v0.4 — Expert Panel Findings & Implementation Plan

> Generated 2026-04-04 from a 4-expert panel review (Product Strategist, DX Engineer, Software Architect, AI/LLM Specialist).

---

## Composite Scores

| Dimension | Product | DX | Architecture | AI/LLM | **Avg** |
|---|---|---|---|---|---|
| **Overall** | 7/10 | 7/10 | 7/10 | 5/10 | **6.5** |
| Market Fit / Usefulness | 7 | — | — | — | |
| Output Quality | — | 7 | — | 5 | |
| Architecture | — | — | 7 | — | |
| Code Quality | — | — | 7 | — | |
| Scalability | — | — | 5 | — | |
| Context Window Efficiency | — | — | — | 4 | |
| Instruction Clarity | — | — | — | 3 | |

---

## The #1 Finding: Descriptive vs. Prescriptive Output

Every expert independently flagged the same issue — the output reads like a **code audit report for humans**, not **instructions for AI agents**.

Current output:
```
- **87% Functions use snake_case** (13/15 files)
  - Examples: `parse_config`, `run_tests`
```

What it should be:
```
- Use snake_case for all function names.
  - Examples: `parse_config`, `run_tests`
```

LLMs are instruction-followers — they don't infer behavioral rules from statistical observations. The percentages, file counts, and "observed in this project" framing add tokens without changing AI behavior.

---

## Key Themes

### 1. The Last Mile Problem (AI + DX)
The analysis engine is solid. The rendering layer is where value is lost. Every token in the context window should pull its weight. Confidence HTML comments, percentage stats, and file counts consume tokens but don't influence code generation. The fix: **imperative rules + concrete code examples + ALWAYS/PREFERRED/NEVER tiers.**

### 2. Platform Absorption Risk (Product, critical)
Anthropic's `/init` already generates `CLAUDE.md`. Cursor has built-in rule generation. The window before platform vendors add "scan my codebase" as a built-in feature is **6-12 months**. The defensible position is being the **cross-platform convention layer** and the **CI integration** that keeps conventions in sync — things no single vendor will build.

### 3. Missing Anti-Patterns (AI)
skillgen tells AI what TO do but never what NOT to do. Worse, conflict notes like "Note: 13% use camelCase" actually *introduce* the anti-pattern into context, increasing the probability the LLM uses it. Recommendation: compute inverse patterns and emit "DO NOT" rules, which LLMs follow very reliably.

### 4. No Feedback Loop (Product + DX)
There's no way to know if the output actually improves AI code quality. No before/after benchmark, no validation step, no "here's what changed." The `--diff` flag compares to "(no guidance)" which isn't meaningful. A `--validate` flag that tests conventions against held-out files would build trust.

### 5. Extractor Duplication (Architecture)
~60% of `ts_extractors.py` (1643 lines) duplicates `analyzer.py` (1497 lines) with minor variations. A per-language `Extractor` protocol/registry would eliminate this and make adding languages a single-file operation.

---

## Implementation Plan

### Phase 1: Imperative Output (Highest Impact) — COMPLETE

**Goal:** Transform output from descriptive statistics to actionable AI instructions.

**Files:** `skillgen/generator.py`, `skillgen/writer.py`, `skillgen/synthesizer.py`, `skillgen/models.py`

**Status:** All 4 items done. 190 tests passing. Changes in 7 files (+483 lines).

#### 1.1 Rewrite `_render_entry` to emit imperative rules — DONE (2026-04-04)
- ~~Transform `"87% Functions use snake_case"` → `"Use snake_case for all function names"`~~
- ~~Drop percentage and file count from rendered output~~
- ~~Add `_to_imperative()` helper to convert observation phrasing to command phrasing~~
- ~~Trust the synthesizer's confidence filtering — if a pattern survived, state it as a rule~~
- Changed all 8 category renderer intros from "observed in" to "Follow these X"
- Removed conflict notes from output (they introduced anti-patterns into LLM context)

#### 1.2 Restructure output into ALWAYS/PREFERRED/NEVER tiers — DONE (2026-04-04)
- ~~In `_format_combined_claude_skill` (writer.py), reorganize content~~
- Added `## ALWAYS`, `## NEVER`, `## PREFERRED` summary sections at top of SKILL.md
- Full category details preserved under `## Category Details` with `###` subsections
- Same tier structure applied to `_format_agents_md_section` for AGENTS.md
- Added `_extract_tier_rules()` to parse and categorize rules from rendered content
- Changed header from "Do not edit manually" to "Regenerate with: skillgen ."

#### 1.3 Add anti-pattern / "DO NOT" rules — DONE (2026-04-04)
- ~~In `synthesizer.py`, compute inverse of dominant patterns during `_deduplicate_and_merge`~~
- ~~If 95% use snake_case, emit: "Do NOT use camelCase for function names"~~
- ~~Remove or suppress conflict notes that introduce minority patterns into context~~
- ~~Store anti-patterns as a new field on `ConventionEntry` or `CategorySummary`~~
- Added `anti_patterns: list[str]` field to `CategorySummary` in models.py
- Added `_compute_anti_patterns()` and `_derive_anti_pattern()` in synthesizer.py
- Only fires when dominant >80% prevalence AND minority <15% prevalence

#### 1.4 Add concrete code snippets per category — DONE (2026-04-04)
- ~~Extend evidence capture in extractors to include 3-5 line code blocks~~
- ~~In each category renderer, emit one representative code example~~
- ~~Even synthetic examples constructed from extracted patterns are valuable~~
- ~~One code block is worth 20 lines of prose for LLM code generation~~
- Added synthetic snippet builders for 6 categories (naming, error handling, testing, imports, documentation, logging)
- Skipped architecture (already has directory tree) and style (config-driven)
- Language-aware: generates Python, TypeScript, JavaScript, Go, Rust, or Java snippets
- Framework-aware: pytest vs unittest, Jest, Go table-driven, zerolog vs zap, etc.
- Added `_clean_evidence()` to strip file references from evidence before use in snippets

### Phase 2: Developer Experience — NOT STARTED

**Goal:** Make skillgen inviting to customize and trustworthy to adopt.

**Files:** `skillgen/writer.py`, `skillgen/cli.py`

#### 2.1 Add `<!-- skillgen:custom -->` preserved sections — TODO
- After each category's generated content, add a preserved marker block:
  ```markdown
  ## Code Style
  [generated content]

  <!-- skillgen:custom:code-style -->
  <!-- Add project-specific style rules here. Preserved on regeneration. -->
  <!-- /skillgen:custom:code-style -->
  ```
- Parse and preserve custom content across regenerations
- Replace "Do not edit manually" with "Generated sections auto-update; custom sections are preserved"

#### 2.2 Add `--validate` flag — TODO
- After generation, sample 5 files NOT in the analysis set
- Check whether generated conventions match the held-out files
- Output confidence score: "Validation: 4/5 files match generated conventions"
- Catches cases where 50-file sample isn't representative

#### 2.3 Add `.gitignore` guidance — TODO
- README should address whether generated files should be committed
- `skillgen init` could offer to add/exclude from `.gitignore`

### Phase 3: CI & Distribution — NOT STARTED

**Goal:** Make skillgen sticky and defensible through CI integration.

#### 3.1 Ship GitHub Action (`skillgen-action`) — TODO
- Runs `skillgen .` on PRs
- Detects convention drift (conventions changed but skill files not regenerated)
- Auto-updates or comments with a diff
- This is the stickiest integration — turns skillgen from one-time generator into living system

#### 3.2 Build before/after benchmark — TODO
- Take 10 popular OSS repos, generate conventions with skillgen
- Measure AI output quality with and without generated files
- Publish results: "Claude Code made X% fewer convention violations with skillgen"
- This is the adoption driver — proof of measurable impact

#### 3.3 Expand plugin distribution — IN PROGRESS
- Claude Code plugin marketplace (done)
- Cursor extension ecosystem (TODO)
- VSCode extension (TODO)

### Phase 4: Architecture Improvements — NOT STARTED

**Goal:** Reduce technical debt and prepare for scale.

**Files:** `skillgen/analyzer.py`, `skillgen/ts_extractors.py`, `skillgen/ts_parser.py`

#### 4.1 Extract per-language Extractor registry — TODO
- Create `Extractor` protocol:
  ```python
  class Extractor(Protocol):
      lang: Language
      def extract(self, source: str, file_path: Path, tree_root: Node | None) -> list[CodePattern]: ...
  ```
- One class per language (`PythonExtractor`, `GoExtractor`, etc.)
- Encapsulates both regex and tree-sitter logic
- Eliminates ~60% duplication between analyzer.py and ts_extractors.py
- Adding a new language becomes a single-file operation

#### 4.2 Single-pass AST walker — TODO
- Current: ~20 `walk_tree` calls per file (O(N * 20) node visits)
- Proposed: single DFS traversal with handler dispatch by node type:
  ```python
  handlers: dict[str, list[Callable[[Node, Language, Path], list[CodePattern]]]]
  ```
- Walk once, invoke all matching handlers per node
- ~20x reduction in tree traversal cost

#### 4.3 Incremental cache — TODO
- Store `.skillgen.cache` (JSON or SQLite) with `{file_path: mtime, patterns: [...]}`
- On subsequent runs, only re-analyze files whose mtime changed
- Essential for CI use case (seconds instead of full scan)
- Sampling approach works but discards information — caching preserves it

#### 4.4 Parallelize file I/O — TODO
- Add `concurrent.futures.ThreadPoolExecutor` for file reading/parsing
- Straightforward win for repos on NFS or slow storage

---

## Strategic Positioning

### Defensible Moats to Build
1. **Cross-platform format expertise** — canonical translator between Claude/Cursor/Copilot convention formats
2. **CI integration stickiness** — once in the pipeline, switching costs go up
3. **Convention drift analytics** — "show me which conventions my AI assistants are violating" (data product)
4. **Community convention graph** — curated index with trust scoring and dependency awareness

### Open Core Model
- **Free (MIT):** CLI tool, local analysis, all output formats
- **Paid:** Team sync across repos, convention drift alerting in CI, compliance dashboard, private skill index for enterprise

### Partnership Strategy
- Position as reference implementation for convention extraction, not competitor to Anthropic/Cursor
- Contribute to their format specs, get listed in their docs
- Best outcome: be the convention layer the AI coding ecosystem standardizes on

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Platform absorption (Anthropic/Cursor build it in) | CRITICAL | CI integration + cross-platform positioning. 6-12 month window. |
| Format war (vendor format changes break output) | HIGH | Abstract format layer, track spec changes, version output format |
| Regex/AST accuracy ceiling | MEDIUM | LLM enrichment as escape hatch, invest in tree-sitter extractors |
| Single maintainer (bus factor = 1) | MEDIUM | Community contributions, plugin ecosystem, documentation |
| No proof of impact | HIGH | Build benchmark suite, publish measurable results |

---

## Success Metrics for v0.4

- [x] Output uses imperative rules (no percentages in rendered output) — Phase 1.1
- [x] ALWAYS/PREFERRED/NEVER tier structure in generated files — Phase 1.2
- [x] Anti-patterns ("DO NOT") included in output — Phase 1.3
- [x] At least 1 concrete code snippet per non-empty category — Phase 1.4
- [ ] Custom section preservation across regeneration — Phase 2.1
- [ ] GitHub Action published — Phase 3.1
- [ ] Before/after benchmark on 3+ repos showing measurable improvement — Phase 3.2
