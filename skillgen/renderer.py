"""Rich terminal UI for skillgen output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from skillgen.models import (
    AnalysisResult,
    GenerationResult,
    OutputFormat,
    PatternCategory,
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
    analysis: AnalysisResult,
    generation: GenerationResult,
    format: OutputFormat = OutputFormat.ALL,
) -> None:
    """Render the --diff comparison table."""
    console.print()
    console.print(Panel("[bold]=== Diff: What the AI Agent Learns ===[/bold]", expand=False))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="bold", min_width=22)
    table.add_column("Without skillgen", style="dim", min_width=24)
    table.add_column("With skillgen", style="green", min_width=45)

    for skill in generation.skills:
        without = _detect_existing_guidance(skill.category, analysis)
        with_sg = _summarize_skill(skill)
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
    analysis: AnalysisResult,
    generation: GenerationResult,
    written_files: list[WrittenFile],
) -> None:
    """Render a stats summary panel."""
    project = analysis.project_info
    langs = ", ".join(project.language_names)
    frameworks = (
        ", ".join(fw.name for fw in project.frameworks) if project.frameworks else "none detected"
    )

    stats_text = (
        f"[bold]Languages:[/bold] {langs}\n"
        f"[bold]Frameworks:[/bold] {frameworks}\n"
        f"[bold]Files scanned:[/bold] {project.total_files}\n"
        f"[bold]Source files:[/bold] {project.source_files}\n"
        f"[bold]Files analyzed:[/bold] {analysis.files_analyzed}\n"
        f"[bold]Patterns detected:[/bold] {len(analysis.patterns)}\n"
        f"[bold]Skills generated:[/bold] {len(generation.skills)}\n"
        f"[bold]Files written:[/bold] {len(written_files)}\n"
        f"[bold]Analysis time:[/bold] {analysis.analysis_duration_seconds:.2f}s\n"
        f"[bold]Generation time:[/bold] {generation.timing_seconds:.2f}s"
    )

    console.print()
    console.print(Panel(stats_text, title="[bold]skillgen Summary[/bold]", expand=False))


def _detect_existing_guidance(category: PatternCategory, analysis: AnalysisResult) -> str:
    """Check if existing skill files provide guidance for this category."""
    root = analysis.project_info.root_path

    # Check for existing skill files
    claude_path = root / ".claude" / "skills" / f"{category.skill_name}.md"
    cursor_path = root / ".cursor" / "rules" / f"{category.skill_name}.mdc"

    if claude_path.exists() or cursor_path.exists():
        return "(existing rules)"

    return "(no guidance)"


def _summarize_skill(skill: SkillDefinition) -> str:
    """One-line summary of a skill's key patterns."""
    # Extract the first non-empty, non-heading line from content
    for line in skill.content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            # Truncate to fit in a table cell
            if len(stripped) > 80:
                return stripped[:77] + "..."
            return stripped

    return skill.description
