"""The radiant CLI — one entry point for humans and agents alike."""

from __future__ import annotations

import json

import typer

from radiant import config, indexer, lint as lint_mod, newpage, search as search_mod

app = typer.Typer(no_args_is_help=True, add_completion=False, help="RadiantBrain CLI")


@app.command()
def new(
    page_type: str = typer.Argument(..., metavar="TYPE", help="Page type, e.g. error_code"),
    slug: str = typer.Argument(..., help="Page slug, e.g. error502"),
    title: str = typer.Option(None, "--title", "-t", help="Page title"),
) -> None:
    """Create a page from its type template."""
    root = config.find_root()
    try:
        dest = newpage.create(root, page_type, slug, title)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"created {dest.relative_to(root)}")


@app.command()
def lint(
    strict: bool = typer.Option(False, "--strict", help="Fail on warnings too"),
) -> None:
    """Validate the knowledge base against docs/02-knowledge-spec.md."""
    root = config.find_root()
    issues = lint_mod.run(root)
    from radiant.kb import load_kb

    n_pages = len(load_kb(root).pages)
    n_err, n_warn = lint_mod.print_report(issues, n_pages)
    if n_err or (strict and n_warn):
        raise typer.Exit(1)


@app.command()
def index() -> None:
    """Rebuild build/index.db from the Markdown knowledge base."""
    root = config.find_root()
    stats = indexer.build_index(root)
    typer.echo(
        f"indexed {stats.pages} pages, {stats.aliases} aliases, "
        f"{stats.edges} edges, {stats.sections} sections -> {config.index_path(root).relative_to(root)}"
    )
    for path in stats.skipped:
        typer.echo(f"warning: skipped (broken frontmatter): {path}", err=True)


@app.command()
def search(
    query: str,
    k: int = typer.Option(10, "-k", help="Max results"),
    json_out: bool = typer.Option(False, "--json", help="JSON output (for agents)"),
    deprecated: bool = typer.Option(False, "--deprecated", help="Include deprecated pages"),
) -> None:
    """Tiered search: exact/alias -> full-text -> graph expansion."""
    root = config.find_root()
    con = search_mod.open_index(root)
    hits = search_mod.search(con, query, k=k, include_deprecated=deprecated)
    if json_out:
        typer.echo(json.dumps([h.to_dict() for h in hits], indent=2))
        return
    if not hits:
        typer.echo("no results")
        raise typer.Exit(1)
    for hit in hits:
        status = "" if hit.status == "active" else f" [{hit.status}]"
        typer.echo(f"{hit.slug}  ({hit.type}){status} — {hit.title}")
        for why in hit.why:
            typer.echo(f"    · {why}")


@app.command()
def ingest(
    source: str = typer.Argument(..., help="File to ingest (PDF, notes, chat export)"),
    plan: str = typer.Option(None, "--plan", help="Apply a pre-written ops plan (YAML) instead of running the Claude extractor"),
    type_hint: str = typer.Option(None, "--type", help="Force parser: pdf | text | chat"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the reconciled plan, change nothing"),
    branch: bool = typer.Option(False, "--branch", help="Apply on a new ingest/<name> git branch and commit"),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if this content was ingested before"),
) -> None:
    """Ingest a source document into the knowledge base (docs/03-pipelines.md)."""
    from pathlib import Path

    from radiant.pipeline import runner

    root = config.find_root()
    result = runner.ingest(
        root,
        source,
        plan_file=Path(plan) if plan else None,
        type_hint=type_hint,
        dry_run=dry_run,
        branch=branch,
        force=force,
    )
    for note in result.notes:
        typer.echo(f"note: {note}")
    if result.plan_yaml:
        typer.echo(result.plan_yaml)
    for page in result.pages:
        typer.echo(f"  {page}")
    typer.echo(f"ingest: {result.status} ({result.source})")
    if result.status == "lint_failed":
        for err in result.lint_errors:
            typer.echo(err, err=True)
        raise typer.Exit(1)


@app.command()
def walk(
    slug: str,
    rel: str = typer.Argument(None, help="Relation to follow, e.g. known_errors"),
    depth: int = typer.Option(1, "--depth", "-d", help="Hops when REL is given"),
) -> None:
    """Explore the knowledge graph around a page."""
    root = config.find_root()
    con = search_mod.open_index(root)
    result = search_mod.walk(con, slug, rel, depth)
    typer.echo(f"{result['slug']}  ({result['type']}) — {result['title']}")
    if rel is None:
        for r, dst in result["outgoing"]:
            typer.echo(f"  ─{r}→ {dst}")
        for r, src in result["incoming"]:
            typer.echo(f"  ←{r}─ {src}")
        if not result["outgoing"] and not result["incoming"]:
            typer.echo("  (no edges)")
    else:
        if not result["levels"]:
            typer.echo(f"  (no {rel} edges)")
        for i, level in enumerate(result["levels"], start=1):
            for node in level:
                typer.echo(f"  {'  ' * (i - 1)}─{rel}→ {node}")


if __name__ == "__main__":
    app()
