# `/skillgen` Hybrid Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the `/skillgen` Claude Code skill to detect the `skillgen` CLI and use its `--json` output as a statistical backbone, reducing context usage from ~10,000 lines to ~1,700 while producing strictly better output.

**Architecture:** Insert Phase 0 (CLI detection + JSON capture) before the existing Phase 1. Add hybrid-mode branches to Phase 2 (fewer files) and Phase 3 (combine CLI stats + Claude semantics). Preserve standalone mode as fallback. One file changes.

**Tech Stack:** Markdown (Claude Code skill prompt). Uses Bash tool for `skillgen --version` and `skillgen . --json`.

---

## File Structure

| File | Action | What changes |
|------|--------|-------------|
| `.claude/skills/skillgen/SKILL.md` | Modify | Insert Phase 0, add hybrid branches to Phase 2 and 3, update context warning and summary |

---

### Task 1: Update Context Warning + Insert Phase 0

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md:20-42`

- [ ] **Step 1: Update the context budget warning (line 22)**

Replace:
```markdown
> **Context budget warning:** This skill reads 15–20 source files. Run it at the start of a session or in a dedicated session to avoid exhausting the context window mid-task.
```

With:
```markdown
> **Context budget:** If the `skillgen` CLI is installed (`pip install skillgen`), this skill uses hybrid mode — CLI stats + 5-8 files (~1,700 lines of context). Without the CLI, standalone mode reads 15-20 files (~10,000 lines). Either way, run at session start or in a dedicated session.
```

- [ ] **Step 2: Update the Full Analysis intro (lines 36-40)**

Replace:
```markdown
## Full Analysis

Execute Phases 1 through 5 in order. Do not skip phases. Print progress headers as you go.

---
```

With:
```markdown
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
4. If the JSON appears truncated (does not end with `}`) or is empty, print "CLI output was invalid. Falling back to standalone mode." and proceed to Phase 1.
5. Otherwise, **skip Phase 1 entirely** and go to **Phase 2 (Hybrid Sampling)**.

**If the command fails (not found, error):**

1. Print: `skillgen CLI not installed. Using standalone mode (reads more files, uses more context).`
2. Print: `Tip: pip install skillgen for faster, more accurate analysis.`
3. Proceed to **Phase 1** (the existing standalone detection).

---
```

- [ ] **Step 3: Verify no duplicate Phase 1 heading**

The existing `### Phase 1: Detect Project Shape` at line 42 remains unchanged. Phase 0 redirects to it on fallback or skips it in hybrid mode.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add Phase 0 CLI detection for hybrid mode"
```

---

### Task 2: Add Hybrid Variant of Phase 2

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md:104-155`

- [ ] **Step 1: Insert hybrid sampling section before existing Phase 2**

Insert BEFORE the existing `### Phase 2: Smart File Sampling` (line 106):

```markdown
### Phase 2 (Hybrid): Focused Semantic Sampling

> **This section runs only in hybrid mode** (Phase 0 detected the CLI). If you're in standalone mode, skip to the next section.

The CLI already scanned up to 50 files per language and reported statistical patterns. You only need to read files for **semantic understanding** — the naming patterns, architectural intent, and contextual guidance that statistics can't capture.

Select **5-8 files** (not 15-20):

1. **Entry point** (1 file): Same heuristic as standalone — `main.py`, `index.ts`, etc. Read first 150 lines.
2. **Source files from different directories** (2-3 files): Look at the CLI JSON's `evidence` fields for filenames that appear frequently. Pick files from different directories. Read first 200 lines each.
3. **Test files** (1-2 files): Pick from the CLI's testing category evidence. Read first 200 lines each.
4. **Model/type file** (1 file): Look for `models.py`, `types.ts`, `schema.go` in the CLI evidence. Read fully if under 200 lines.

**Anti-rules still apply:** no generated files, no migrations, no lock files, no vendored code.

Print the file list:
```
Hybrid mode — reading 6 files for semantic enrichment:
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
```

- [ ] **Step 2: Rename the existing Phase 2 heading**

Change the existing heading at (previously line 106):
```markdown
### Phase 2: Smart File Sampling
```
To:
```markdown
### Phase 2 (Standalone): Smart File Sampling
```

Add at the top of this section:
```markdown
> **This section runs only in standalone mode** (CLI not detected in Phase 0). If you're in hybrid mode, you already did Phase 2 above.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add hybrid Phase 2 with reduced file sampling"
```

---

### Task 3: Add Hybrid Variant of Phase 3

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md:157-243`

- [ ] **Step 1: Insert hybrid extraction section before existing Phase 3**

Insert BEFORE the existing `### Phase 3: Convention Extraction Checklist` (line 157):

```markdown
### Phase 3 (Hybrid): Combined Extraction

> **This section runs only in hybrid mode.** If standalone, skip to the next section.

You have TWO data sources for each category:
1. **CLI data** — exact statistics: prevalence percentages, file counts, config values, evidence strings, conflict annotations
2. **Your reading** — semantic understanding from the 5-8 files you just read

**Combination rules:**

1. **Quantitative claims MUST come from CLI data:**
   - Write: "**82% use snake_case** (14/17 files)"
   - NOT: "most functions use snake_case" (vague — you didn't scan all files)

2. **Semantic insight comes from your reading:**
   - Write: "specifically the **verb_noun** pattern: `get_user`, `create_order`, `validate_input`"
   - NOT: just listing the CLI's evidence strings verbatim

3. **Config values come from CLI data verbatim:**
   - Write: "**Configured in ruff:** line-length = 100, select = E, F, W, I, N, UP, B, SIM, RUF"
   - These are in `config_settings` in the JSON.

4. **Architectural guidance comes from your reading:**
   - Write: "New API endpoints go in `app/routers/` following the existing `APIRouter` pattern"
   - The CLI can't infer this — only you can, from reading the code.

5. **Conflicts — explain with context:**
   - If the CLI JSON shows a `conflict` field on an entry, explain it using what you read:
   - Write: "82% snake_case, but `legacy/old_api.py` uses camelCase (appears to be pre-refactor code)"

6. **Don't just reformat the JSON.** Add genuine semantic value. If you can't add anything beyond what the CLI says for a category, use the CLI data as-is — don't pad with generic advice.

7. **Process ALL categories the CLI reported.** Also check if your reading reveals patterns the CLI missed (e.g., decorator conventions, architectural patterns). Add them as new entries.

Walk through the 8 categories in order: naming, error handling, testing, imports, documentation, architecture, code style, logging. For each, combine CLI stats + your semantic insight following the rules above.

After extraction, proceed to **Phase 4** (same for both modes).

---

### Phase 3 (Standalone): Convention Extraction Checklist
```

- [ ] **Step 2: Rename the existing Phase 3 heading**

Change:
```markdown
### Phase 3: Convention Extraction Checklist
```
To:
```markdown
### Phase 3 (Standalone): Convention Extraction Checklist
```

Add at the top:
```markdown
> **This section runs only in standalone mode.** If hybrid, you already did Phase 3 above.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat(plugin): add hybrid Phase 3 combining CLI stats with Claude semantics"
```

---

### Task 4: Update Phase 5 Summary + Final Commit

**Files:**
- Modify: `.claude/skills/skillgen/SKILL.md:305-330`

- [ ] **Step 1: Update the summary template**

Replace the summary block (lines 309-328) with:

```markdown
If hybrid mode was used, print:
```
/skillgen complete! (hybrid mode: CLI stats + Claude semantics)

Generated N skill files in .claude/skills/:
  naming-conventions.md      (XX lines)
  error-handling.md          (XX lines)
  ...

Skipped: [categories skipped — "no patterns" or "hand-written file"]

Powered by skillgen CLI (statistical analysis across NN files) + Claude (semantic enrichment).
To share with your team: git add .claude/skills/ && git commit -m "Add AI skill files"
```

If standalone mode was used, print:
```
/skillgen complete! (standalone mode)

Generated N skill files in .claude/skills/:
  naming-conventions.md      (XX lines)
  ...

Skipped: [categories skipped]

These conventions are now active for this and all future sessions.
To share with your team: git add .claude/skills/ && git commit -m "Add AI skill files"

Tip: pip install skillgen for faster, more accurate analysis (hybrid mode).
```
```

- [ ] **Step 2: Run `/skillgen` smoke test**

In a new Claude Code session, type `/skillgen` and verify:
- Phase 0 detects the CLI (since `skillgen` is installed in this project)
- Runs `skillgen . --json` and parses the output
- Reads only 5-8 files
- Generates skill files combining stats + semantics
- Summary says "hybrid mode"

- [ ] **Step 3: Final commit**

```bash
git add .claude/skills/skillgen/SKILL.md
git commit -m "feat: /skillgen hybrid mode — CLI stats + Claude semantics

When skillgen CLI is installed, /skillgen now:
- Runs skillgen . --json for statistical backbone (<1s)
- Reads only 5-8 files instead of 15-20 (6x less context)
- Combines exact stats with Claude's semantic understanding
- Falls back to standalone mode when CLI not installed"
```

---

## Self-Review

**Spec coverage:**
- Phase 0 CLI detection: Task 1
- Hybrid Phase 2 (5-8 files): Task 2
- Hybrid Phase 3 (combine CLI + reading): Task 3
- Phase 5 summary update: Task 4
- Standalone fallback preserved: Tasks 2-3 (renamed, not deleted)
- Context budget warning: Task 1
- Error handling (truncated JSON, empty output): Task 1 Step 2
- Enrich subcommand unchanged: Not touched

**Placeholder scan:** No TBD/TODO. All prompt text is complete.

**Consistency:** Phase references ("Phase 2 Hybrid" / "Phase 2 Standalone") are consistent. "Proceed to Phase 3 (Hybrid Extraction)" in Task 2 matches Task 3's heading.
