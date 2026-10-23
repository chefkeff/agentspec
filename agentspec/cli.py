import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .parser import parse_spec, ParseError
from .transpiler import to_markdown
from .benchmark import benchmark_spec, count_tokens
from .packer import pack_for_task, format_subagent_prompt
from .patcher import patch_file, PatchError
from .linter import lint_spec
from .ingester import ingest_codebase
from .dashboard import generate_html_dashboard
from .compressor import summarize_markdown_to_aspec
from .mcp import run_mcp_server
from .scheduler import get_task_schedule

console = Console()

STARTER_TEMPLATE = """@spec 0.1
@meta app: "auth-gateway" | stack: "fastapi+redis" | owner: "infra-team"

# 1. CONTRACTS & TYPES
!type Token = { id: str, perms: str[], exp: int }
!type LoginReq = { email: str, password_hash: str }

!svc AuthService:
  login(req: LoginReq) -> Token
  verify(token_str: str) -> bool
  revoke(token_id: str) -> bool

# 2. RATIONALES & INVARIANTS
!why auth: "stateless JWT to allow horizontal scaling behind load balancer"
!rule sec: "never persist plaintext passwords; bcrypt work factor >= 12"
!invariant rate_limit: "5 failed attempts per IP per 10min window"

# 3. TASK EXECUTION DAG
[x] T1: initialize fastapi skeleton & docker-compose
[>] T2: implement AuthService token generation [after: T1]
[ ] T3: add redis blacklist for revoked tokens [after: T2]
[ ] T4: setup rate limiting middleware [after: T2]
[ ] T5: end-to-end integration tests [after: T3, T4]
"""

def cmd_check(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        dag_errors = doc.validate_dag()

        if dag_errors:
            console.print("[bold red]DAG Validation Failed:[/bold red]")
            for err in dag_errors:
                console.print(f"  [red]•[/red] {err}")
            sys.exit(1)

        console.print(f"[bold green]✔ Valid agentspec:[/bold green] '{filepath}'")
        console.print(f"  • Spec Version: [cyan]{doc.version}[/cyan]")
        console.print(f"  • Types: [cyan]{len(doc.types)}[/cyan]")
        console.print(f"  • Services: [cyan]{len(doc.services)}[/cyan]")
        console.print(f"  • Invariants/Rules: [cyan]{len(doc.invariants)}[/cyan]")
        console.print(f"  • Tasks: [cyan]{len(doc.tasks)}[/cyan]")

    except ParseError as pe:
        console.print(f"[bold red]Syntax Error:[/bold red] {pe}")
        sys.exit(1)

def cmd_render(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        md = to_markdown(doc)

        if args.out:
            out_path = Path(args.out)
            out_path.write_text(md, encoding="utf-8")
            console.print(f"[bold green]Rendered markdown saved to:[/bold green] {out_path}")
        else:
            print(md)
    except Exception as e:
        console.print(f"[bold red]Rendering error:[/bold red] {e}")
        sys.exit(1)

def cmd_benchmark(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        results = benchmark_spec(content)

        table = Table(title=f"Token Density Benchmark: {filepath.name}", header_style="bold magenta")
        table.add_column("Tokenizer / Encoding", style="cyan")
        table.add_column(".aspec Tokens", justify="right", style="green")
        table.add_column("Markdown Tokens", justify="right", style="yellow")
        table.add_column("Tokens Saved", justify="right", style="bold green")
        table.add_column("Compression Ratio", justify="right", style="bold blue")

        for enc_name, res in results.items():
            table.add_row(
                enc_name,
                str(res.aspec_tokens),
                str(res.markdown_tokens),
                f"-{res.saved_tokens}",
                f"{res.reduction_percent:.1f}% reduction"
            )

        console.print(table)
        console.print(Panel(
            "[dim]agentspec stores dense structural contracts and DAGs natively. "
            "Markdown rendering is derived deterministically when human review is needed.[/dim]",
            title="💡 Token Optimization Insight"
        ))

    except Exception as e:
        console.print(f"[bold red]Benchmark error:[/bold red] {e}")
        sys.exit(1)

def cmd_pack(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        
        full_tokens = count_tokens(content, "cl100k_base")
        prune = not getattr(args, "no_prune", False)
        packed_doc = pack_for_task(doc, args.task, prune_contracts=prune)
        packed_aspec = packed_doc.to_aspec()
        packed_tokens = count_tokens(packed_aspec, "cl100k_base")
        savings = ((full_tokens - packed_tokens) / full_tokens * 100) if full_tokens > 0 else 0

        if args.raw:
            output = packed_aspec
        else:
            output = format_subagent_prompt(doc, args.task, prune_contracts=prune)

        if args.out:
            Path(args.out).write_text(output, encoding="utf-8")
            console.print(f"[bold green]Packed context saved to:[/bold green] {args.out}")
        else:
            print(output)

        console_err = Console(stderr=True)
        console_err.print(f"\n[dim cyan]⚡ Subagent Slice Stats: {packed_tokens} tokens (reduced by {savings:.1f}% vs full spec {full_tokens} tok)[/dim cyan]")

    except Exception as e:
        console.print(f"[bold red]Pack error:[/bold red] {e}")
        sys.exit(1)

def cmd_patch(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    mutations = []
    if args.set:
        mutations.extend(args.set)
    if args.add_task:
        for t in args.add_task:
            mutations.append(f"+task {t}")
    if args.add_why:
        for w in args.add_why:
            mutations.append(f"+why {w}")
    if args.add_rule:
        for r in args.add_rule:
            mutations.append(f"+rule {r}")

    if not mutations:
        console.print("[yellow]Warning: No mutations provided. Use --set, --add-task, --add-why, or --add-rule.[/yellow]")
        return

    try:
        verify = getattr(args, "verify", False)
        patch_file(filepath, mutations, verify=verify)
        console.print(f"[bold green]✔ Successfully patched '{filepath}':[/bold green]")
        for m in mutations:
            console.print(f"  • Applied: [cyan]{m}[/cyan]")
    except PatchError as pe:
        console.print(f"[bold red]Patch Error:[/bold red] {pe}")
        sys.exit(1)

def cmd_lint(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        issues = lint_spec(doc)

        if not issues:
            console.print(f"[bold green]✔ All clean![/bold green] No lint or workflow issues in '{filepath}'.")
            return

        has_errors = any(i.severity == "ERROR" for i in issues)
        table = Table(title=f"Workflow & Spec Lint: {filepath.name}", header_style="bold magenta")
        table.add_column("Level", style="bold")
        table.add_column("Code", style="dim")
        table.add_column("Message")

        for i in issues:
            lvl_color = "red" if i.severity == "ERROR" else ("yellow" if i.severity == "WARNING" else "blue")
            table.add_row(f"[{lvl_color}]{i.severity}[/{lvl_color}]", i.code, i.message)

        console.print(table)
        if has_errors:
            sys.exit(1)

    except Exception as e:
        console.print(f"[bold red]Lint error:[/bold red] {e}")
        sys.exit(1)

def cmd_ingest(args):
    target_path = Path(args.path)
    if not target_path.exists():
        console.print(f"[bold red]Error:[/bold red] Path '{target_path}' not found.")
        sys.exit(1)

    try:
        doc = ingest_codebase(target_path)
        aspec_out = doc.to_aspec()
        out_file = Path(args.out or f"{target_path.name or 'project'}.aspec")
        out_file.write_text(aspec_out, encoding="utf-8")

        console.print(f"[bold green]✔ Successfully ingested codebase into:[/bold green] '{out_file}'")
        console.print(f"  • Extracted Types: [cyan]{len(doc.types)}[/cyan]")
        console.print(f"  • Extracted Services: [cyan]{len(doc.services)}[/cyan]")
        console.print(f"  • Initial Tasks: [cyan]{len(doc.tasks)}[/cyan]")

    except Exception as e:
        console.print(f"[bold red]Ingest error:[/bold red] {e}")
        sys.exit(1)

def cmd_view(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        html = generate_html_dashboard(doc, content)

        out_path = Path(args.out or f"{filepath.stem}_dashboard.html")
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[bold green]✔ Interactive HTML Dashboard saved to:[/bold green] {out_path}")
        console.print(f"  [dim]Open this file in any web browser to view the live Mermaid DAG and task slices.[/dim]")

    except Exception as e:
        console.print(f"[bold red]View error:[/bold red] {e}")
        sys.exit(1)

def cmd_compress(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        content = filepath.read_text(encoding="utf-8")
        raw_tokens = count_tokens(content, "cl100k_base")
        aspec_draft = summarize_markdown_to_aspec(content, app_name=filepath.stem)
        compressed_tokens = count_tokens(aspec_draft, "cl100k_base")
        savings = ((raw_tokens - compressed_tokens) / raw_tokens * 100) if raw_tokens > 0 else 0

        out_path = Path(args.out or f"{filepath.stem}.aspec")
        out_path.write_text(aspec_draft, encoding="utf-8")

        console.print(f"[bold green]✔ Compressed markdown into agentspec:[/bold green] '{out_path}'")
        console.print(f"  • Raw Markdown: [yellow]{raw_tokens} tokens[/yellow]")
        console.print(f"  • Compressed .aspec: [green]{compressed_tokens} tokens[/green]")
        console.print(f"  • Token Savings: [bold cyan]{savings:.1f}% reduction[/bold cyan]")

    except Exception as e:
        console.print(f"[bold red]Compress error:[/bold red] {e}")
        sys.exit(1)

def cmd_mcp(args):
    console_err = Console(stderr=True)
    console_err.print("[dim cyan]Starting agentspec MCP stdio server...[/dim cyan]")
    run_mcp_server()

def cmd_init(args):
    target = Path(args.filename or "project.aspec")
    if target.exists():
        console.print(f"[bold red]Error:[/bold red] '{target}' already exists.")
        sys.exit(1)

    target.write_text(STARTER_TEMPLATE, encoding="utf-8")
    console.print(f"[bold green]Initialized new agentspec file at:[/bold green] {target}")

def cmd_ready(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        import json
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        schedule = get_task_schedule(doc)

        if args.json:
            data = {
                "ready_tasks": [
                    {"id": t.id, "title": t.title, "touches": t.touches, "refs": t.refs, "test": t.test_cmd}
                    for t in schedule.ready_tasks
                ],
                "in_progress": [{"id": t.id, "title": t.title} for t in schedule.in_progress_tasks],
                "blocked_tasks": [
                    {"id": t.id, "title": t.title, "missing_deps": [d for d in t.dependencies if d not in {x.id for x in schedule.completed_tasks}]}
                    for t in schedule.blocked_tasks
                ],
                "parallel_batches": [
                    {
                        "batch_index": b.batch_index,
                        "tasks": [{"id": t.id, "title": t.title, "touches": t.touches} for t in b.tasks],
                        "touched_files": list(b.touched_files)
                    }
                    for b in schedule.parallel_batches
                ],
                "file_conflicts": schedule.file_conflicts
            }
            print(json.dumps(data, indent=2))
            return

        console.print(f"\n[bold cyan]🚀 Multi-Agent Swarm Dispatcher:[/bold cyan] {filepath.name}")
        console.print(f"Completed: [green]{len(schedule.completed_tasks)}[/green] | In Progress: [yellow]{len(schedule.in_progress_tasks)}[/yellow] | Ready: [bold green]{len(schedule.ready_tasks)}[/bold green] | Blocked: [dim]{len(schedule.blocked_tasks)}[/dim]\n")

        if schedule.file_conflicts:
            console.print("[bold red]⚠ File Contention Detected:[/bold red]")
            for f, tids in schedule.file_conflicts.items():
                console.print(f"  • File '[bold]{f}[/bold]' contended by tasks: [yellow]{', '.join(tids)}[/yellow] (isolated into separate execution tiers)")
            console.print("")

        if not schedule.ready_tasks:
            if schedule.in_progress_tasks:
                console.print("[yellow]No new tasks ready. Currently awaiting in-progress tasks.[/yellow]")
            elif not schedule.blocked_tasks:
                console.print("[bold green]✔ All tasks in DAG are completed![/bold green]")
            else:
                console.print("[red]Deadlock: No tasks ready but incomplete tasks remain. Check dependencies.[/red]")
            return

        table = Table(title="Conflict-Free Parallel Execution Batches", header_style="bold magenta")
        table.add_column("Tier", justify="center", style="bold cyan", width=8)
        table.add_column("Task ID", style="bold yellow", width=10)
        table.add_column("Title", style="white")
        table.add_column("File Locks", style="green")
        table.add_column("Verification", style="dim")

        for b in schedule.parallel_batches:
            for i, t in enumerate(b.tasks):
                tier_str = f"Batch {b.batch_index}" if i == 0 else ""
                touches_str = ", ".join(t.touches) if t.touches else "[dim]unrestricted[/dim]"
                test_str = "[cyan]configured[/cyan]" if t.test_cmd else "[dim]none[/dim]"
                table.add_row(tier_str, t.id, t.title, touches_str, test_str)

        console.print(table)
        console.print(f"\n[dim green]💡 All tasks in Batch 1 can be dispatched to parallel subagents concurrently without git merge conflicts.[/dim green]\n")

    except Exception as e:
        console.print(f"[bold red]Scheduler error:[/bold red] {e}")
        sys.exit(1)

def cmd_test(args):
    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[bold red]Error:[/bold red] File '{filepath}' not found.")
        sys.exit(1)

    try:
        import subprocess
        content = filepath.read_text(encoding="utf-8")
        doc = parse_spec(content)
        task_map = {t.id: t for t in doc.tasks}

        target_tasks = []
        if args.task:
            if args.task not in task_map:
                console.print(f"[bold red]Error:[/bold red] Task '{args.task}' not found in spec.")
                sys.exit(1)
            target_tasks.append(task_map[args.task])
        else:
            target_tasks = [t for t in doc.tasks if t.test_cmd]

        if not target_tasks:
            console.print("[yellow]No tasks with [test: ...] verification commands found.[/yellow]")
            return

        all_passed = True
        for t in target_tasks:
            if not t.test_cmd:
                console.print(f"[yellow]Task {t.id} has no [test: ...] command configured.[/yellow]")
                continue

            console.print(f"Running verification for [bold]{t.id}[/bold]: [cyan]{t.test_cmd}[/cyan] ...")
            res = subprocess.run(t.test_cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                console.print(f"  [bold green]✔ PASSED[/bold green]")
            else:
                all_passed = False
                console.print(f"  [bold red]✖ FAILED (exit code {res.returncode})[/bold red]")
                if res.stdout:
                    console.print(f"  [dim]{res.stdout.strip()}[/dim]")
                if res.stderr:
                    console.print(f"  [red]{res.stderr.strip()}[/red]")

        if not all_passed:
            sys.exit(1)

    except Exception as e:
        console.print(f"[bold red]Test execution error:[/bold red] {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(prog="aspec", description="agentspec: Token-efficient agent state framework")
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommands")

    # check
    p_check = subparsers.add_parser("check", help="Validate an .aspec file and its task DAG")
    p_check.add_argument("file", help="Path to .aspec file")

    # render
    p_render = subparsers.add_parser("render", help="Transpile .aspec into formatted Markdown")
    p_render.add_argument("file", help="Path to .aspec file")
    p_render.add_argument("--out", "-o", help="Output file path (default stdout)")

    # benchmark
    p_bm = subparsers.add_parser("benchmark", help="Benchmark token savings vs Markdown")
    p_bm.add_argument("file", help="Path to .aspec file")

    # pack
    p_pack = subparsers.add_parser("pack", help="Generate minimal subagent context slice for a task")
    p_pack.add_argument("file", help="Path to .aspec file")
    p_pack.add_argument("--task", "-t", required=True, help="Target task ID (e.g. T3)")
    p_pack.add_argument("--no-prune", action="store_true", help="Keep all types and services in context slice")
    p_pack.add_argument("--raw", action="store_true", help="Output raw .aspec slice without prompt wrapper")
    p_pack.add_argument("--out", "-o", help="Output file path")

    # patch
    p_patch = subparsers.add_parser("patch", help="Apply in-place mutations to a spec file")
    p_patch.add_argument("file", help="Path to .aspec file")
    p_patch.add_argument("--set", "-s", action="append", help="Set task status (e.g. T2=done)")
    p_patch.add_argument("--verify", action="store_true", help="Run [test: ...] verification gate before marking task done")
    p_patch.add_argument("--add-task", action="append", help="Add new task (e.g. 'T7: title [after: T6]')")
    p_patch.add_argument("--add-why", action="append", help="Add rationale (e.g. 'key: reason')")
    p_patch.add_argument("--add-rule", action="append", help="Add rule (e.g. 'key: constraint')")

    # ready
    p_ready = subparsers.add_parser("ready", help="List unblocked tasks and conflict-free parallel swarm batches")
    p_ready.add_argument("file", help="Path to .aspec file")
    p_ready.add_argument("--json", action="store_true", help="Output JSON for orchestrator agents")

    # test
    p_test = subparsers.add_parser("test", help="Execute [test: ...] verification gates")
    p_test.add_argument("file", help="Path to .aspec file")
    p_test.add_argument("--task", "-t", help="Target task ID (runs all testable tasks if omitted)")

    # lint
    p_lint = subparsers.add_parser("lint", help="Check workflow hygiene, dead types, and state guards")
    p_lint.add_argument("file", help="Path to .aspec file")

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Auto-extract types and services from a Python codebase")
    p_ingest.add_argument("path", nargs="?", default=".", help="Directory or python file to scan")
    p_ingest.add_argument("--out", "-o", help="Output .aspec filename")

    # view
    p_view = subparsers.add_parser("view", help="Generate interactive standalone HTML dashboard with Mermaid")
    p_view.add_argument("file", help="Path to .aspec file")
    p_view.add_argument("--out", "-o", help="Output HTML filename")

    # compress
    p_comp = subparsers.add_parser("compress", help="Compress verbose Markdown prose into a dense .aspec draft")
    p_comp.add_argument("file", help="Path to markdown file")
    p_comp.add_argument("--out", "-o", help="Output .aspec filename")

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Run Model Context Protocol stdio server")

    # init
    p_init = subparsers.add_parser("init", help="Create a starter .aspec template")
    p_init.add_argument("filename", nargs="?", default="project.aspec", help="Target filename")

    args = parser.parse_args()

    dispatch = {
        "check": cmd_check,
        "render": cmd_render,
        "benchmark": cmd_benchmark,
        "pack": cmd_pack,
        "patch": cmd_patch,
        "ready": cmd_ready,
        "test": cmd_test,
        "lint": cmd_lint,
        "ingest": cmd_ingest,
        "view": cmd_view,
        "compress": cmd_compress,
        "mcp": cmd_mcp,
        "init": cmd_init,
    }

    if args.subcommand in dispatch:
        dispatch[args.subcommand](args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
