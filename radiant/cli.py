"""The radiant CLI — one entry point for humans and agents alike."""

from __future__ import annotations

import functools
import json
from pathlib import Path

import typer

from radiant import config, indexer, lint as lint_mod, newpage, search as search_mod

app = typer.Typer(no_args_is_help=True, add_completion=False, help="RadiantBrain CLI")


def _clean_errors(fn):
    """Turn RuntimeError (e.g. missing API credentials) into a tidy CLI error
    instead of a traceback."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RuntimeError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1)

    return wrapper


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
@_clean_errors
def ingest(
    source: str = typer.Argument(..., help="File to ingest (PDF, notes, chat export)"),
    plan: str = typer.Option(None, "--plan", help="Apply a pre-written ops plan (YAML) instead of running the Claude extractor"),
    type_hint: str = typer.Option(None, "--type", help="Force parser: pdf | text | chat"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the reconciled plan, change nothing"),
    branch: bool = typer.Option(False, "--branch", help="Apply on a new ingest/<name> git branch and commit"),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if this content was ingested before"),
) -> None:
    """Ingest a source document into the knowledge base (docs/03-pipelines.md)."""
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
@_clean_errors
def learn(
    ticket: int = typer.Option(..., "--ticket", help="Ticket id to learn from"),
    plan: str = typer.Option(None, "--plan", help="Apply a pre-written ops plan instead of the Claude extractor"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the reconciled plan, change nothing"),
    branch: bool = typer.Option(False, "--branch", help="Apply on a learn/ticket-<id> branch and commit"),
) -> None:
    """Fold a resolved ticket's solution back into the knowledge base (docs/03)."""
    from radiant.pipeline import learn as learn_mod

    root = config.find_root()
    result = learn_mod.learn(
        root, ticket,
        plan_file=Path(plan) if plan else None,
        dry_run=dry_run, branch=branch,
    )
    for note in result.notes:
        typer.echo(f"note: {note}")
    if result.plan_yaml:
        typer.echo(result.plan_yaml)
    for page in result.pages:
        typer.echo(f"  {page}")
    typer.echo(f"learn: {result.status} (ticket #{result.ticket_id})")
    if result.status == "lint_failed":
        for err in result.lint_errors:
            typer.echo(err, err=True)
        raise typer.Exit(1)


tickets_app = typer.Typer(no_args_is_help=True, help="Manage the operational ticket store")
app.add_typer(tickets_app, name="tickets")


@tickets_app.command("import")
def tickets_import(file: str = typer.Argument(..., help="YAML file: one ticket or a list")) -> None:
    """Import tickets (with message threads) from a YAML file."""
    from radiant import tickets as ts

    root = config.find_root()
    ids = ts.import_file(root, Path(file))
    typer.echo(f"imported {len(ids)} ticket(s): {', '.join('#' + str(i) for i in ids)}")


@tickets_app.command("list")
def tickets_list(
    status: str = typer.Option(None, "--status", help="Filter by status"),
    learn_status: str = typer.Option(None, "--learn-status", help="Filter by learn_status"),
) -> None:
    """List tickets."""
    from radiant import tickets as ts

    root = config.find_root()
    rows = ts.list_tickets(root, status=status, learn_status=learn_status)
    if not rows:
        typer.echo("no tickets")
        return
    for t in rows:
        errs = ",".join(t.error_slugs) or "-"
        typer.echo(f"#{t.id} [{t.status}/{t.learn_status}] robot={t.robot_slug or '-'} "
                   f"errors={errs} — {t.summary or ''}")


@app.command()
@_clean_errors
def curator(
    create_stubs: bool = typer.Option(False, "--create-stubs", help="(reserved) create draft stub pages — Phase 6"),
) -> None:
    """Show the curator backlog: questions the knowledge base couldn't answer."""
    from radiant.agent import curator as curator_mod

    root = config.find_root()
    gaps = curator_mod.backlog(root)
    if not gaps:
        typer.echo("backlog empty — no unanswered questions logged")
        return
    typer.echo(f"{len(gaps)} documentation gap(s):")
    for g in gaps:
        typer.echo(f"  - {g.question}  ({g.asked_at})")
    if create_stubs:
        typer.echo("note: automatic stub creation is deferred to the curator agent (Phase 6)")


@app.command()
@_clean_errors
def ask(
    question: str,
    agent: str = typer.Option("support", "--agent", help="Which agent (support | chief-of-staff)"),
    json_out: bool = typer.Option(False, "--json", help="Emit the raw answer contract as JSON"),
    no_log: bool = typer.Option(False, "--no-log", help="Do not record the answer"),
) -> None:
    """Ask an agent a question; every answer is citation-verified (docs/05)."""
    from radiant.agent import answerlog, support
    from radiant.agent.contract import format_answer
    from radiant.agent.retrieval import ScopedRetriever
    from radiant.settings import load_settings

    root = config.find_root()
    settings = load_settings(root)
    agent_cfg = settings.agent(agent)
    con = search_mod.open_index(root)
    retriever = ScopedRetriever(con, agent_cfg)
    responder = support.ClaudeResponder(agent_cfg)

    result = support.answer_question(retriever, responder, settings, question)
    if not no_log:
        answerlog.record(root, agent, question, result.answer)

    if json_out:
        typer.echo(result.answer.model_dump_json(indent=2))
    else:
        typer.echo(format_answer(result.answer))
    if result.answer.confidence == "none":
        raise typer.Exit(2)  # honest refusal is a distinct exit code


@app.command()
@_clean_errors
def eval(
    path: str = typer.Option("evals/questions.yaml", "--file", help="Golden-set YAML"),
) -> None:
    """Run the golden-set evaluation for the support agent (docs/05)."""
    from radiant.agent import evals, support
    from radiant.agent.retrieval import ScopedRetriever
    from radiant.settings import load_settings

    root = config.find_root()
    settings = load_settings(root)
    cases = evals.load_cases(root / path if not Path(path).is_absolute() else Path(path))
    con = search_mod.open_index(root)

    def retriever_for(agent_name: str) -> ScopedRetriever:
        return ScopedRetriever(con, settings.agent(agent_name))

    report = evals.EvalReport([])
    for case in cases:
        r = evals.run_case(retriever_for(case.agent), support.ClaudeResponder(settings.agent(case.agent)), settings, case)
        report.results.append(r)
        mark = "PASS" if r.passed else "FAIL"
        typer.echo(f"[{mark}] {case.id}: {case.question}")
        for reason in r.reasons:
            typer.echo(f"       - {reason}")
    typer.echo(f"\n{report.passed}/{report.total} passed")
    if not report.ok:
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
