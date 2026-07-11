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
def index(
    embed: bool = typer.Option(False, "--embed", help="Also build the semantic vector tier (docs/04 tier 3)"),
    provider: str = typer.Option(None, "--embed-provider", help="voyage | local (default: voyage if VOYAGE_API_KEY, else local)"),
) -> None:
    """Rebuild build/index.db from the Markdown knowledge base."""
    root = config.find_root()
    embedder = None
    if embed:
        from radiant.vectors import get_embedder

        embedder = get_embedder(provider)
        if embedder.name == "local":
            typer.echo("note: local embedder is lexical, not semantic — set VOYAGE_API_KEY "
                       "for real semantic search", err=True)
    stats = indexer.build_index(root, embedder=embedder)
    vec = f", {stats.vectors} vectors" if stats.vectors else ""
    typer.echo(
        f"indexed {stats.pages} pages, {stats.aliases} aliases, "
        f"{stats.edges} edges, {stats.sections} sections{vec} -> {config.index_path(root).relative_to(root)}"
    )
    for path in stats.skipped:
        typer.echo(f"warning: skipped (broken frontmatter): {path}", err=True)


@app.command()
def search(
    query: str,
    k: int = typer.Option(10, "-k", help="Max results"),
    json_out: bool = typer.Option(False, "--json", help="JSON output (for agents)"),
    deprecated: bool = typer.Option(False, "--deprecated", help="Include deprecated pages"),
    semantic: bool = typer.Option(False, "--semantic", help="Force the semantic vector tier (needs an embedded index)"),
) -> None:
    """Tiered search: exact/alias -> full-text -> graph -> optional semantic."""
    root = config.find_root()
    con = search_mod.open_index(root)
    embedder = None
    if semantic:
        from radiant.vectors import get_embedder

        embedder = get_embedder()
    hits = search_mod.search(con, query, k=k, include_deprecated=deprecated,
                             embedder=embedder, semantic=semantic)
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
    ticket: int = typer.Option(None, "--ticket", help="Ticket id to learn from"),
    pending: bool = typer.Option(False, "--pending", help="Process all closed tickets awaiting learning"),
    plan: str = typer.Option(None, "--plan", help="Apply a pre-written ops plan instead of the Claude extractor"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the reconciled plan, change nothing"),
    branch: bool = typer.Option(False, "--branch", help="Apply on a learn/ticket-<id> branch and commit"),
) -> None:
    """Fold a resolved ticket's solution back into the knowledge base (docs/03)."""
    from radiant.pipeline import learn as learn_mod

    root = config.find_root()
    if pending:
        results = learn_mod.learn_pending(root, branch=branch)
        if not results:
            typer.echo("no closed tickets awaiting learning")
            return
        for r in results:
            typer.echo(f"ticket #{r.ticket_id}: {r.status}"
                       + (f" ({r.merge_category})" if r.merge_category else ""))
        return
    if ticket is None:
        typer.echo("error: give --ticket <id> or --pending", err=True)
        raise typer.Exit(1)
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
def note(
    page_type: str = typer.Argument(..., metavar="TYPE", help="investor | competitor | meeting | idea | research"),
    slug: str = typer.Argument(..., help="Page slug (meetings are auto date-prefixed)"),
    text: str = typer.Argument(..., help="The note to append"),
    section: str = typer.Option(None, "--section", "-s", help="Target section (default depends on type)"),
    title: str = typer.Option(None, "--title", "-t", help="Title if the page is created"),
    on: str = typer.Option(None, "--on", help="Date override (YYYY-MM-DD)"),
) -> None:
    """Capture a dated note onto a personal page, creating it if needed."""
    from radiant import notes

    root = config.find_root()
    try:
        dest, created = notes.add_note(root, page_type, slug, text,
                                       section=section, title=title, on=on)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)
    verb = "created + noted" if created else "noted"
    typer.echo(f"{verb}: {dest.relative_to(root)}")


@app.command()
def digest(
    topic: str = typer.Argument(None, help="Preset: concerns | competitors | actions | ideas"),
    page_type: str = typer.Option(None, "--type", help="Page type (with --section)"),
    section: str = typer.Option(None, "--section", "-s", help="Section to collate"),
    timeline: bool = typer.Option(False, "--timeline", help="Show dated entries newest-first across all pages"),
) -> None:
    """Collate a section across all pages of a type — the monitoring view."""
    from radiant import digest as dig

    root = config.find_root()
    if topic:
        if topic not in dig.PRESETS:
            typer.echo(f"error: unknown preset {topic!r} (have: {', '.join(dig.PRESETS)})", err=True)
            raise typer.Exit(1)
        page_type, section = dig.PRESETS[topic]
    if not (page_type and section):
        typer.echo("error: give a preset, or both --type and --section", err=True)
        raise typer.Exit(1)

    d = dig.collate(root, page_type, section)
    if not d.entries:
        typer.echo(f"no entries under '{section}' across {page_type} pages")
        return
    typer.echo(f"{section} — across {page_type} pages ({len(d.entries)} entries)\n")
    if timeline:
        for e in d.chronological():
            typer.echo(f"  {e.when}  [{e.page}] {e.text}")
        return
    for slug, entries in d.by_page().items():
        typer.echo(f"{slug} ({entries[0].page_title}):")
        for e in entries:
            when = f"{e.when} — " if e.when else ""
            typer.echo(f"  - {when}{e.text}")
        typer.echo("")


@app.command()
def review(
    since: str = typer.Option(None, "--since", help="Only include dated entries on/after YYYY-MM-DD"),
    write: bool = typer.Option(False, "--write", help="Save as a dated research page under personal/research/"),
) -> None:
    """Weekly review: recurring concerns, competitor moves, actions, ideas."""
    from radiant import review as rev

    root = config.find_root()
    if write:
        dest = rev.write_review(root, since=since)
        typer.echo(f"wrote {dest.relative_to(root)}")
        return
    body, _ = rev.build_review(root, since=since)
    typer.echo(body)


@app.command()
@_clean_errors
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8787, "--port", "-p", help="Port"),
) -> None:
    """Launch the RadiantBrain ops console (globe + neural graph dashboard)."""
    from radiant import webapp

    root = config.find_root()
    if not config.index_path(root).exists():
        typer.echo("note: no index yet — building one so the graph has data", err=True)
        indexer.build_index(root)
    webapp.serve(root, host=host, port=port)


events_app = typer.Typer(no_args_is_help=True, help="Manage the world-event feed (globe)")
app.add_typer(events_app, name="events")


@events_app.command("import")
def events_import(file: str = typer.Argument(..., help="JSON file of events")) -> None:
    """Import world events from a JSON file."""
    from radiant import events as ev

    root = config.find_root()
    n = ev.import_file(root, Path(file))
    typer.echo(f"imported {n} event(s)")


@events_app.command("list")
def events_list() -> None:
    """List events currently in the feed."""
    from radiant import events as ev

    root = config.find_root()
    stored = ev.list_events(root)
    for e in ev.feed(root):
        typer.echo(f"#{e.id} [{e.category}] {e.headline}  ({e.occurred_at or '—'})")
    if not stored:
        typer.echo("(built-in sample feed — add real events via cron jobs or `radiant events import`)")


@app.command()
def doctor() -> None:
    """Check that operational slug references resolve against the KB (docs/06)."""
    from radiant import integrity

    root = config.find_root()
    dangling = integrity.check_slugs(root)
    if not dangling:
        typer.echo("ok: all operational slug references resolve")
        return
    for d in dangling:
        typer.echo(str(d), err=True)
    typer.echo(f"{len(dangling)} dangling reference(s)", err=True)
    raise typer.Exit(1)


@app.command()
def ops(
    error: str = typer.Argument(None, help="Error slug to show prior resolutions for"),
) -> None:
    """Operational views: prior ticket resolutions and error trends (docs/05, docs/06)."""
    from radiant import opsviews

    root = config.find_root()
    resolutions = opsviews.error_resolutions(root, error)
    if error:
        typer.echo(f"Prior resolutions for {error}:")
        if not resolutions:
            typer.echo("  (none on record)")
        for r in resolutions:
            who = f" [{r.distributor}]" if r.distributor else ""
            typer.echo(f"  - {r.resolution}{who}  ({r.closed_at or 'n/a'})")
        return
    freq = opsviews.error_frequency(root)
    typer.echo("Error frequency across tickets:")
    for slug, n in freq.items():
        typer.echo(f"  {slug}: {n}")


@app.command()
def dashboard(
    out: str = typer.Option(None, "--out", "-o", help="Output HTML path (default build/dashboard.html)"),
) -> None:
    """Generate the read-only operations dashboard (docs/07 Phase 5)."""
    from radiant import dashboard as dash

    root = config.find_root()
    path = dash.write(root, Path(out) if out else None)
    typer.echo(f"wrote {path.relative_to(root) if path.is_relative_to(root) else path}")


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
    responder = support.make_responder(agent_cfg)

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
