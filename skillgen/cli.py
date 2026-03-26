"""CLI entry point for skillgen."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from skillgen import __version__
from skillgen.analyzer import analyze_project
from skillgen.detector import detect_project
from skillgen.generator import GenerationMode, generate_skills
from skillgen.models import OutputFormat
from skillgen.renderer import (
    create_progress,
    render_diff,
    render_dry_run,
    render_stats,
    render_summary,
)
from skillgen.writer import write_skills

app = typer.Typer(
    name="skillgen",
    help="Analyze a codebase and generate AI agent skill files.",
    add_completion=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
)

_console = Console()


def _version_callback(value: bool) -> None:
    if value:
        _console.print(f"skillgen {__version__}")
        raise typer.Exit()


@app.command()
def main(
    path: Path = typer.Argument(
        ".",
        help="Path to the codebase to analyze.",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.ALL,
        "--format",
        "-f",
        help="Target AI tool format: claude, cursor, or all.",
    ),
    diff: bool = typer.Option(
        False,
        "--diff",
        help="Show what the AI agent learns vs. blank-slate.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview generated files without writing to disk.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis steps.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress all output except errors.",
    ),
    llm: bool = typer.Option(
        False,
        "--llm",
        help="Use LLM for enhanced skill generation (requires API key).",
    ),
    llm_provider: str | None = typer.Option(
        None,
        "--llm-provider",
        help="LLM provider: 'anthropic' or 'openai'. Auto-detected from env by default.",
    ),
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Analyze a codebase and generate AI agent skill files.

    [bold]Examples:[/bold]

        skillgen ./my-project

        skillgen ./my-project --format claude --dry-run

        skillgen . --diff --verbose
    """
    # --- Path validation ---
    resolved = path.resolve()
    if not resolved.exists():
        _console.print(f"[red]Error:[/red] {path} does not exist.")
        raise typer.Exit(code=1)
    if resolved.is_file():
        _console.print(
            f"[red]Error:[/red] {path} is a file, not a directory. "
            "Point skillgen at a project root."
        )
        raise typer.Exit(code=1)
    if not resolved.is_dir():
        _console.print(f"[red]Error:[/red] {path} is not a directory.")
        raise typer.Exit(code=1)

    try:
        progress = create_progress(quiet=quiet)

        with progress:
            # Phase 1: Detect
            task_detect = progress.add_task("Scanning files and detecting languages...", total=1)
            project_info = detect_project(resolved, verbose=verbose)
            progress.update(task_detect, completed=1)

            if not project_info.languages:
                progress.stop()
                _console.print(
                    "[red]Error:[/red] No supported language detected. "
                    "Supported: Python, TypeScript, Java, Go, Rust, C++."
                )
                raise typer.Exit(code=1)

            if verbose and not quiet:
                progress.console.print(
                    f"  [dim]Detected: {', '.join(project_info.language_names)}[/dim]"
                )

            # Phase 2: Analyze
            task_analyze = progress.add_task("Analyzing patterns...", total=1)
            analysis = analyze_project(project_info, verbose=verbose)
            progress.update(task_analyze, completed=1)

            if verbose and not quiet:
                progress.console.print(
                    f"  [dim]{len(analysis.patterns)} patterns found in "
                    f"{analysis.files_analyzed} files[/dim]"
                )

            # Phase 3: Generate
            task_generate = progress.add_task("Generating skills...", total=1)
            mode = GenerationMode.LLM if llm else GenerationMode.LOCAL
            generation = generate_skills(
                analysis,
                mode=mode,
                llm_provider=llm_provider,
            )
            progress.update(task_generate, completed=1)

            # Phase 4: Write
            task_write = progress.add_task("Writing files...", total=1)
            written_files = write_skills(
                generation,
                target_dir=resolved,
                output_format=format,
                dry_run=dry_run,
            )
            progress.update(task_write, completed=1)

        # Phase 5: Render
        if dry_run:
            render_dry_run(generation, quiet=quiet)

        if diff:
            render_diff(analysis, generation, format=format)

        if not quiet:
            render_summary(written_files, dry_run=dry_run)
            if verbose:
                render_stats(analysis, generation, written_files)

    except typer.Exit:
        raise
    except KeyboardInterrupt:
        _console.print("\n[yellow]Interrupted.[/yellow]")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        _console.print(f"[red]Internal error:[/red] {exc}")
        if verbose:
            _console.print_exception()
        raise typer.Exit(code=2) from exc


if __name__ == "__main__":
    app()
