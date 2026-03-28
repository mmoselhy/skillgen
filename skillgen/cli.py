"""CLI entry point for skillgen."""

from __future__ import annotations

import dataclasses
import enum
import json
from pathlib import Path

import typer
from rich.console import Console

from skillgen import __version__
from skillgen.analyzer import analyze_project
from skillgen.detector import detect_project
from skillgen.generator import GenerationMode, generate_skills
from skillgen.models import OutputFormat, WrittenFile
from skillgen.renderer import (
    create_progress,
    render_diff,
    render_dry_run,
    render_stats,
    render_summary,
)
from skillgen.synthesizer import synthesize
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


def _json_serializer(obj: object) -> object:
    """Custom JSON serializer for Path and Enum types."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _make_json_serializable(obj: object) -> object:
    """Recursively convert dataclass dicts to JSON-serializable form.

    Handles dict keys that are Enum types (e.g., PatternCategory keys in categories).
    """
    if isinstance(obj, dict):
        return {
            (k.value if isinstance(k, enum.Enum) else k): _make_json_serializable(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_make_json_serializable(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    return obj


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
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output analysis as JSON and exit.",
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
    no_tree_sitter: bool = typer.Option(
        False,
        "--no-tree-sitter",
        help="Disable tree-sitter parsing even if installed (use regex fallback).",
    ),
    enrich: bool = typer.Option(
        False,
        "--enrich",
        help="Search online index for community skills matching this project.",
    ),
    apply_enrich: bool = typer.Option(
        False,
        "--apply",
        help="Download and install matched community skills (use with --enrich).",
    ),
    pick: str | None = typer.Option(
        None,
        "--pick",
        help="Comma-separated skill numbers to cherry-pick (e.g., --pick 1,3).",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Force re-fetch of online skill index, ignoring cache.",
    ),
    trust: str | None = typer.Option(
        None,
        "--trust",
        help="Filter by trust tier: official, community, contributed, or all. Default: all.",
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

    # --- Enrich flag validation ---
    if apply_enrich and not enrich:
        _console.print("[red]Error:[/red] Use --enrich --apply together.")
        raise typer.Exit(code=1)
    if pick is not None and not apply_enrich:
        _console.print("[red]Error:[/red] Use --pick with --enrich --apply.")
        raise typer.Exit(code=1)

    pick_indices: list[int] | None = None
    if pick is not None:
        try:
            pick_indices = [int(x.strip()) for x in pick.split(",")]
        except ValueError:
            _console.print(
                "[red]Error:[/red] --pick must be comma-separated numbers (e.g., --pick 1,3)."
            )
            raise typer.Exit(code=1) from None

    trust_filter: set[str] | None = None
    if trust is not None:
        valid_tiers = {"official", "community", "contributed", "all"}
        if trust.lower() not in valid_tiers:
            _console.print(
                "[red]Error:[/red] --trust must be one of: official, community, contributed, all."
            )
            raise typer.Exit(code=1)
        if trust.lower() != "all":
            trust_filter = {trust.lower()}

    try:
        progress = create_progress(quiet=quiet or json_output)

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
            analysis = analyze_project(
                project_info, verbose=verbose, use_tree_sitter=not no_tree_sitter
            )
            progress.update(task_analyze, completed=1)

            if verbose and not quiet:
                progress.console.print(
                    f"  [dim]{len(analysis.patterns)} patterns found in "
                    f"{analysis.files_analyzed} files[/dim]"
                )

            # Phase 2.5: Synthesize
            task_synth = progress.add_task("Synthesizing conventions...", total=1)
            conventions = synthesize(analysis)
            progress.update(task_synth, completed=1)

            if verbose and not quiet:
                cat_count = len(conventions.categories)
                entry_count = sum(len(s.entries) for s in conventions.categories.values())
                cfg_count = len(conventions.config_settings)
                progress.console.print(
                    f"  [dim]{entry_count} conventions in {cat_count} categories, "
                    f"{cfg_count} config values[/dim]"
                )

            # --json: serialize and exit
            if json_output:
                progress.stop()
                raw = dataclasses.asdict(conventions)
                data = _make_json_serializable(raw)
                print(json.dumps(data, default=_json_serializer, indent=2))
                raise typer.Exit(code=0)

            # Phase 2.75: Enrich (optional, network)
            enrich_result = None
            enrich_written: list[WrittenFile] = []
            if enrich:
                from skillgen.enricher import apply as enrich_apply
                from skillgen.enricher import search as enrich_search

                task_enrich = progress.add_task("Searching community skills...", total=1)
                enrich_result = enrich_search(
                    conventions,
                    cache_dir=None,
                    no_cache=no_cache,
                    trust_filter=trust_filter,
                )
                progress.update(task_enrich, completed=1)

                if apply_enrich:
                    selected_entries = enrich_result.matched
                    if pick_indices:
                        max_idx = len(enrich_result.matched)
                        invalid = [i for i in pick_indices if i < 1 or i > max_idx]
                        if invalid:
                            progress.stop()
                            _console.print(
                                f"[red]Error:[/red] Invalid --pick values: {invalid}. "
                                f"Only {max_idx} skills matched (valid range: 1-{max_idx})."
                            )
                            raise typer.Exit(code=1)
                        selected_entries = [enrich_result.matched[i - 1] for i in pick_indices]

                    task_apply = progress.add_task("Installing community skills...", total=1)
                    enrich_written = enrich_apply(
                        entries=selected_entries,
                        target_dir=resolved,
                        output_format=format,
                        no_cache=no_cache,
                    )
                    progress.update(task_apply, completed=1)

            # Phase 3: Generate (now uses conventions)
            task_generate = progress.add_task("Generating skills...", total=1)
            mode = GenerationMode.LLM if llm else GenerationMode.LOCAL
            generation = generate_skills(
                conventions,
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
            render_diff(conventions, generation, format=format)

        if not quiet:
            render_summary(written_files, dry_run=dry_run)
            if verbose:
                render_stats(conventions, generation, written_files)

        # Render enrichment results
        if enrich and enrich_result is not None:
            from skillgen.renderer import render_enrich_applied, render_enrich_preview

            if apply_enrich:
                render_enrich_applied(enrich_written)
            else:
                render_enrich_preview(enrich_result)

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
