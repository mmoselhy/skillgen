"""Rich terminal UI for skillgen output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from skillgen.models import (
    CategorySummary,
    EnrichmentResult,
    GenerationResult,
    OutputFormat,
    PatternCategory,
    ProjectConventions,
    SkillDefinition,
    WrittenFile,
)

console = Console()


def create_progress(quiet: bool = False) -> Progress:
    """Create a Rich progress bar with spinners for each phase."""
    if quiet:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=Console(quiet=True),
        )
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )


def render_summary(written_files: list[WrittenFile], dry_run: bool = False) -> None:
    """Render the final summary table of generated files."""
    table = Table(
        title="Generated Skill Files" + (" (dry run)" if dry_run else ""),
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("File", style="cyan", min_width=40)
    table.add_column("Format", style="green", justify="center")
    table.add_column("Lines", style="yellow", justify="right")

    for wf in sorted(written_files, key=lambda f: str(f.path)):
        table.add_row(str(wf.path), wf.format.title(), str(wf.line_count))

    console.print()
    console.print(table)
    console.print(
        f"\n[bold green]Done![/bold green] "
        f"{len(written_files)} file(s) {'would be ' if dry_run else ''}generated."
    )


def render_diff(
    conventions: ProjectConventions,
    generation: GenerationResult,
    format: OutputFormat = OutputFormat.ALL,
) -> None:
    """Render the --diff comparison table using ProjectConventions data."""
    console.print()
    console.print(Panel("[bold]=== Diff: What the AI Agent Learns ===[/bold]", expand=False))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="bold", min_width=22)
    table.add_column("Without skillgen", style="dim", min_width=24)
    table.add_column("With skillgen", style="green", min_width=45)

    for skill in generation.skills:
        without = _detect_existing_guidance(skill.category, conventions)
        summary = conventions.categories.get(skill.category)
        with_sg = _summarize_convention(skill, summary)
        style = "yellow" if without != "(no guidance)" else "green"
        table.add_row(
            skill.category.display_name,
            without,
            Text(with_sg, style=style),
        )

    console.print(table)
    console.print()


def render_dry_run(generation: GenerationResult, quiet: bool = False) -> None:
    """Render dry-run output: file contents to stdout."""
    for skill in generation.skills:
        if not quiet:
            console.print(
                f"\n--- {skill.name} (dry run, not written) ---",
                style="bold blue",
            )
        console.print(skill.content)
        if not quiet:
            console.print()


def render_stats(
    conventions: ProjectConventions,
    generation: GenerationResult,
    written_files: list[WrittenFile],
) -> None:
    """Render a stats summary panel."""
    project = conventions.project_info
    langs = ", ".join(project.language_names)
    frameworks = (
        ", ".join(fw.name for fw in project.frameworks) if project.frameworks else "none detected"
    )
    entry_count = sum(len(s.entries) for s in conventions.categories.values())
    config_count = len(conventions.config_settings)

    stats_text = (
        f"[bold]Languages:[/bold] {langs}\n"
        f"[bold]Frameworks:[/bold] {frameworks}\n"
        f"[bold]Files scanned:[/bold] {project.total_files}\n"
        f"[bold]Source files:[/bold] {project.source_files}\n"
        f"[bold]Files analyzed:[/bold] {conventions.files_analyzed}\n"
        f"[bold]Conventions synthesized:[/bold] {entry_count}\n"
        f"[bold]Config values parsed:[/bold] {config_count}\n"
        f"[bold]Skills generated:[/bold] {len(generation.skills)}\n"
        f"[bold]Files written:[/bold] {len(written_files)}\n"
        f"[bold]Analysis time:[/bold] {conventions.analysis_duration_seconds:.2f}s\n"
        f"[bold]Synthesis time:[/bold] {conventions.synthesis_duration_seconds:.2f}s\n"
        f"[bold]Generation time:[/bold] {generation.timing_seconds:.2f}s"
    )

    console.print()
    console.print(Panel(stats_text, title="[bold]skillgen Summary[/bold]", expand=False))


def _detect_existing_guidance(
    category: PatternCategory, conventions: ProjectConventions
) -> str:
    """Check if existing skill files provide guidance for this category."""
    root = conventions.project_info.root_path

    # Check for existing skill files.
    claude_path = root / ".claude" / "skills" / f"{category.skill_name}.md"
    cursor_path = root / ".cursor" / "rules" / f"{category.skill_name}.mdc"

    if claude_path.exists() or cursor_path.exists():
        return "(existing rules)"

    return "(no guidance)"


def _summarize_convention(
    skill: SkillDefinition,
    summary: CategorySummary | None,
) -> str:
    """One-line summary of a skill's key conventions with stats."""
    if summary is None:
        return skill.description

    parts: list[str] = []

    # Count entries.
    entry_count = len(summary.entries)
    if entry_count > 0:
        parts.append(f"{entry_count} rules")

    # Show top entry's prevalence if available.
    if summary.entries:
        top = summary.entries[0]
        if top.total_files > 0:
            pct = top.file_count * 100 // top.total_files
            parts.append(f"{pct}% {top.description}")

    # Show config values count.
    if summary.config_values:
        parts.append(f"{len(summary.config_values)} config values")

    if parts:
        result = " | ".join(parts)
        if len(result) > 80:
            return result[:77] + "..."
        return result

    return skill.description


def render_enrich_preview(result: EnrichmentResult) -> None:
    """Show a Rich table when --enrich is used without --apply."""
    if not result.matched and result.errors:
        console.print(f"\n[yellow]Warning:[/yellow] {result.errors[0]}")
        return
    if not result.matched:
        console.print("\n[dim]No community skills found.[/dim]")
        return

    table = Table(
        title="Community Skills Matching This Project",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="bold", justify="right")
    table.add_column("Skill", style="cyan", min_width=25)
    table.add_column("Categories", style="green")
    table.add_column("Description", style="dim")

    for idx, entry in enumerate(result.matched, start=1):
        categories = ", ".join(entry.categories)
        table.add_row(str(idx), entry.name, categories, entry.description)

    console.print()
    console.print(table)

    if result.skipped_categories:
        console.print(
            f"\n[dim]Skipped (already covered locally): "
            f"{', '.join(result.skipped_categories)}[/dim]"
        )

    console.print(
        "\n[bold]To install:[/bold] skillgen . --enrich --apply"
    )
    console.print(
        "[bold]To pick:[/bold] skillgen . --enrich --apply --pick 1,2"
    )


def render_enrich_applied(written: list[WrittenFile]) -> None:
    """Show result after --enrich --apply."""
    if not written:
        console.print("\n[dim]No community skill files written.[/dim]")
        return

    table = Table(
        title="Community Skill Files Installed",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("File", style="cyan", min_width=40)
    table.add_column("Format", style="green", justify="center")
    table.add_column("Lines", style="yellow", justify="right")

    for wf in sorted(written, key=lambda f: str(f.path)):
        table.add_row(str(wf.path), wf.format.title(), str(wf.line_count))

    console.print()
    console.print(table)
    console.print(
        f"\n[bold green]Done![/bold green] "
        f"{len(written)} community skill file(s) installed."
    )
