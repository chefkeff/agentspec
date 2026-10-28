"""
A/B harness: several Claude Code agents build the same project in a shared
directory, coordinating either through agentspec or through a plain shared
checklist. Each run is graded by hidden acceptance tests the agents never see.

    eval/.venv/bin/python eval/run_ab.py --runs 1 --label pilot
    eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --runs 4 --label xl
    eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --restart-turns 12 --label xl-restart

With --restart-turns, a first wave of agents is cut off after that many turns
each (leaving work half-claimed), then a fresh wave of agents takes over. The
fresh wave is told the first was stopped, unless --restart-silent is given; then
abandoned claims are only recovered through agentspec's claim leases (set short
with --lease) or by the agents noticing on their own.

    eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --restart-turns 12 \
        --restart-silent --lease 180 --label xl-restart-silent
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from agentspec import parse_spec, to_markdown  # noqa: E402
from agentspec.models import TaskStatus  # noqa: E402

VENV_BIN = EVAL_DIR / ".venv" / "bin"
CONDITIONS = ("agentspec", "checklist")
# Set once any agent hits an API error (e.g. a usage limit); later runs are skipped.
STOP = threading.Event()

ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(python3 *)", "Bash(aspec *)", "Bash(sleep *)", "Bash(ls *)", "Bash(cat *)",
]

WORKER_PROMPT = (
    "You are {name}, one of {n} agents working at the same time in this directory on the same "
    "Python project. Read PROTOCOL.md and follow it exactly to pick up, implement and complete tasks. "
    "Use only the Python standard library. Keep going until every task is done, then reply with a "
    "one-line summary of the tasks you completed."
)

RESTART_NOTE = (
    " Note: an earlier group of agents ({previous}) was stopped partway through. Any task still marked "
    "as in progress by one of them was abandoned: give it back as described in PROTOCOL.md so it can be "
    "picked up again. Files they were editing may be half-finished."
)


@dataclass
class Project:
    name: str
    dir: Path
    spec_text: str
    work_tasks: List[str]
    hidden_file_to_task: Dict[str, str]

    @classmethod
    def load(cls, name: str) -> "Project":
        pdir = EVAL_DIR / "projects" / name
        spec_text = (pdir / "spec.aspec").read_text(encoding="utf-8")
        doc = parse_spec(spec_text)
        work = [t.id for t in doc.tasks if t.status != TaskStatus.DONE]
        hidden = {}
        for f in sorted((pdir / "hidden").glob("test_t*_*.py")):
            m = re.match(r"test_t(\d+)_", f.name)
            hidden[f.stem] = f"T{m.group(1)}"
        return cls(name, pdir, spec_text, work, hidden)


def setup_run(run_dir: Path, condition: str, project: Project, lease: float = None) -> None:
    shutil.copytree(project.dir / "project", run_dir)
    shutil.copy(EVAL_DIR / "protocols" / f"{condition}.md", run_dir / "PROTOCOL.md")
    if condition == "agentspec":
        spec_text = project.spec_text
        if lease:
            spec_text = re.sub(r"^(@meta .*)$", rf'\1 | lease: "{lease:g}s"', spec_text, count=1, flags=re.M)
        (run_dir / "project.aspec").write_text(spec_text, encoding="utf-8")
    else:
        doc = parse_spec(project.spec_text)
        (run_dir / "PLAN.md").write_text(to_markdown(doc), encoding="utf-8")
        todo = ["# TODO", ""] + [
            f"- [{'x' if t.status == TaskStatus.DONE else ' '}] {t.id}: {t.title}" for t in doc.tasks
        ]
        (run_dir / "TODO.md").write_text("\n".join(todo) + "\n", encoding="utf-8")


def launch_wave(run_dir: Path, names: List[str], n_agents: int, args, deadline: float,
                max_turns: int = None, note: str = "") -> List[str]:
    """Run one wave of agents to completion (or the deadline). Returns names that timed out."""
    env = dict(os.environ, PATH=f"{VENV_BIN}{os.pathsep}{os.environ['PATH']}")
    procs = []
    for name in names:
        log = open(run_dir.parent / f"{run_dir.name}.{name}.jsonl", "w")
        cmd = [
            "claude", "-p", WORKER_PROMPT.format(name=name, n=n_agents) + note,
            "--model", args.model,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk",
            "--allowedTools", *ALLOWED_TOOLS,
            "--strict-mcp-config", "--setting-sources", "project",
            "--no-session-persistence",
            "--max-budget-usd", str(args.budget),
        ]
        if max_turns:
            cmd += ["--max-turns", str(max_turns)]
        procs.append((name, subprocess.Popen(cmd, cwd=run_dir, env=env, stdout=log,
                                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL), log))

    timed_out = []
    for name, proc, log in procs:
        try:
            proc.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out.append(name)
        log.close()
    return timed_out


def _touches_repo(tool_input: str, run_dir: Path) -> bool:
    """Does a tool call reach into the agentspec repo (outside the agent's own run directory)?"""
    own = str(run_dir.resolve())
    if own + "/.." in tool_input:
        return True
    return str(REPO_ROOT) in tool_input.replace(own, "")


def parse_agent_log(path: Path, run_dir: Path) -> dict:
    stats = {"cost_usd": 0.0, "turns": 0, "is_error": None, "subtype": None, "edited_files": [],
             "denials": 0, "result": None, "input_tokens": 0, "output_tokens": 0, "api_error": None,
             "repo_access": [], "lease_releases": 0}
    edited = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "user" and "Released expired claim" in line:
            stats["lease_releases"] += 1
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and _touches_repo(json.dumps(block.get("input", {})), run_dir):
                    stats["repo_access"].append(f"{block.get('name')}: {json.dumps(block.get('input'))[:200]}")
                if block.get("type") == "tool_use" and block.get("name") in ("Edit", "Write", "MultiEdit"):
                    fp = block.get("input", {}).get("file_path")
                    if fp:
                        edited.append(fp)
        elif ev.get("type") == "result":
            usage = ev.get("usage", {})
            stats.update(
                cost_usd=ev.get("total_cost_usd") or 0.0,
                turns=ev.get("num_turns") or 0,
                is_error=ev.get("is_error"),
                subtype=ev.get("subtype"),
                api_error=ev.get("api_error_status"),
                denials=len(ev.get("permission_denials") or []),
                result=(ev.get("result") or "")[:300],
                input_tokens=(usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                              + usage.get("cache_creation_input_tokens", 0)),
                output_tokens=usage.get("output_tokens", 0),
            )
    stats["edited_files"] = edited
    return stats


def run_hidden_tests(run_dir: Path, project: Project) -> dict:
    junit = run_dir.parent / f"{run_dir.name}.hidden.xml"
    env = dict(os.environ, SHOP_ROOT=str(run_dir))
    subprocess.run(
        [str(VENV_BIN / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
         f"--junitxml={junit}", str(project.dir / "hidden")],
        env=env, capture_output=True, text=True, timeout=300,
    )
    per_task = {t: {"passed": 0, "total": 0} for t in project.work_tasks}
    if junit.exists():
        root = ET.parse(junit).getroot()
        for case in root.iter("testcase"):
            module = case.get("classname", "").split(".")[-1]
            task = project.hidden_file_to_task.get(module)
            if not task:
                continue
            per_task[task]["total"] += 1
            if not any(child.tag in ("failure", "error", "skipped") for child in case):
                per_task[task]["passed"] += 1
        # A module that fails to import shows up as a single collection error
        for case in root.iter("testcase"):
            if case.get("classname", "") == "" and any(c.tag == "error" for c in case):
                name = case.get("name", "")
                for module, task in project.hidden_file_to_task.items():
                    if module in name and per_task[task]["total"] == 0:
                        per_task[task]["total"] = 1
    return per_task


def task_states(run_dir: Path, condition: str, project: Project) -> Dict[str, str]:
    """Final state of each open task as recorded by the agents: todo, in_progress or done."""
    states = {t: "todo" for t in project.work_tasks}
    if condition == "agentspec":
        try:
            doc = parse_spec((run_dir / "project.aspec").read_text(encoding="utf-8"))
        except Exception:
            return {t: "unparseable" for t in project.work_tasks}
        for t in doc.tasks:
            if t.id in states:
                states[t.id] = t.status.value
        return states
    todo = (run_dir / "TODO.md").read_text(encoding="utf-8")
    for t in project.work_tasks:
        if re.search(rf"^\s*-\s*\[[xX]\]\s*{t}\b", todo, re.M):
            states[t] = "done"
        elif re.search(rf"^\s*-\s*\[~\]\s*{t}\b", todo, re.M):
            states[t] = "in_progress"
    return states


def score_run(run_dir: Path, condition: str, project: Project, launch: dict) -> dict:
    agents = {p.name.split(".")[1]: parse_agent_log(p, run_dir)
              for p in sorted(run_dir.parent.glob(f"{run_dir.name}.agent-*.jsonl"))}
    hidden = run_hidden_tests(run_dir, project)
    tasks_passing = [t for t, r in hidden.items() if r["total"] and r["passed"] == r["total"]]
    states = task_states(run_dir, condition, project)
    done = [t for t, s in states.items() if s == "done"]

    def rel(fp):
        try:
            return str(Path(fp).resolve().relative_to(run_dir.resolve()))
        except ValueError:
            return fp

    edits_by_file = {}
    for name, a in agents.items():
        for fp in {rel(f) for f in a["edited_files"]}:
            edits_by_file.setdefault(fp, []).append(name)

    stopped_on_purpose = set(launch.get("first_wave", []))
    return {
        "condition": condition,
        "project": project.name,
        "run": run_dir.name,
        "restart": bool(stopped_on_purpose),
        "restart_silent": launch.get("silent", False),
        "lease_seconds": launch.get("lease"),
        "lease_releases": sum(a["lease_releases"] for a in agents.values()),
        # An API error (usage limit, overload) means agents were cut off by the
        # platform rather than by the task, so the run says nothing about either condition.
        "invalid": sorted({f"API error {a['api_error']}" for a in agents.values() if a["api_error"]}
                          | ({"agent accessed the agentspec repo (hidden tests, reference, other projects)"}
                             if any(a["repo_access"] for a in agents.values()) else set())),
        "repo_access": {n: a["repo_access"][:5] for n, a in agents.items() if a["repo_access"]},
        "wall_seconds": launch["wall_seconds"],
        "timed_out": launch["timed_out"],
        "cost_usd": round(sum(a["cost_usd"] for a in agents.values()), 3),
        "turns": sum(a["turns"] for a in agents.values()),
        "input_tokens": sum(a["input_tokens"] for a in agents.values()),
        "output_tokens": sum(a["output_tokens"] for a in agents.values()),
        "hidden_tests_passed": sum(r["passed"] for r in hidden.values()),
        "hidden_tests_total": sum(r["total"] for r in hidden.values()),
        "tasks_total": len(project.work_tasks),
        "tasks_passing": sorted(tasks_passing),
        "all_tasks_pass": len(tasks_passing) == len(project.work_tasks),
        "marked_done": sorted(done),
        "false_done": sorted(set(done) - set(tasks_passing)),
        "left_in_progress": sorted(t for t, s in states.items() if s == "in_progress"),
        "left_todo": sorted(t for t, s in states.items() if s == "todo"),
        "src_files_edited_by_multiple_agents": {f: a for f, a in edits_by_file.items()
                                                if f.startswith("src/") and len(a) > 1},
        "test_files_edited": sorted(f for f in edits_by_file if f.startswith("tests/")),
        "state_file_hand_edits": sorted(f for f in edits_by_file if f == "project.aspec")
        if condition == "agentspec" else [],
        "permission_denials": sum(a["denials"] for a in agents.values()),
        "agent_errors": [n for n, a in agents.items()
                         if n not in stopped_on_purpose and (a["is_error"] or a["is_error"] is None)],
        "hidden_per_task": hidden,
    }


def do_run(condition: str, index: int, project: Project, args) -> dict:
    run_dir = args.workdir / f"{args.label}-{condition}-{index}"
    if STOP.is_set():
        print(f"[skip]  {run_dir.name}: stopped after an API error in an earlier run", flush=True)
        return None
    if run_dir.exists():
        shutil.rmtree(run_dir)
    for old in args.workdir.glob(f"{run_dir.name}.*"):
        old.unlink()
    setup_run(run_dir, condition, project, lease=args.lease)
    print(f"[start] {run_dir.name}", flush=True)

    n = args.agents
    start = time.time()
    deadline = start + args.timeout
    launch = {"timed_out": [], "silent": bool(args.restart_turns and args.restart_silent),
              "lease": args.lease if condition == "agentspec" else None}
    if args.restart_turns:
        first = [f"agent-{k}" for k in range(1, n + 1)]
        launch["timed_out"] += launch_wave(run_dir, first, n, args, deadline, max_turns=args.restart_turns)
        launch["first_wave"] = first
        second = [f"agent-{k}" for k in range(n + 1, 2 * n + 1)]
        note = "" if args.restart_silent else RESTART_NOTE.format(previous=f"agent-1 to agent-{n}")
        launch["timed_out"] += launch_wave(run_dir, second, n, args, deadline, note=note)
    else:
        launch["timed_out"] += launch_wave(run_dir, [f"agent-{k}" for k in range(1, n + 1)], n, args, deadline)
    launch["wall_seconds"] = round(time.time() - start, 1)

    result = score_run(run_dir, condition, project, launch)
    if launch["wall_seconds"] > args.timeout + 300:
        # The deadline is checked against wall-clock time, so this means the machine
        # slept (or the harness stalled) and agents were cut off for reasons unrelated to the task.
        result["invalid"].append(f"run took {launch['wall_seconds']:.0f}s, far over the {args.timeout}s cap "
                                 "(machine asleep?)")
    if result["invalid"]:
        STOP.set()
        print(f"[invalid] {run_dir.name}: {'; '.join(result['invalid'])}; not counted, stopping", flush=True)
        (args.workdir / f"{run_dir.name}.invalid.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return None
    (args.results / f"{run_dir.name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[done]  {run_dir.name}: {result['hidden_tests_passed']}/{result['hidden_tests_total']} hidden tests, "
          f"{len(result['tasks_passing'])}/{result['tasks_total']} tasks, ${result['cost_usd']}, "
          f"{result['wall_seconds']}s", flush=True)
    return result


def summarize(results: list) -> str:
    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    def rng(xs, fmt="{:.0f}"):
        return f"{fmt.format(min(xs))}–{fmt.format(max(xs))}" if xs else "-"

    by_cond = {c: [r for r in results if r["condition"] == c] for c in CONDITIONS}
    n_hidden = max((r["hidden_tests_total"] for r in results), default=0)
    n_tasks = max((r["tasks_total"] for r in results), default=0)
    lines = ["| Metric | " + " | ".join(CONDITIONS) + " |", "| :--- | " + " | ".join("---:" for _ in CONDITIONS) + " |"]
    rows = [
        ("Runs", lambda rs: f"{len(rs)}"),
        (f"All {n_tasks} tasks pass (runs)", lambda rs: f"{sum(r['all_tasks_pass'] for r in rs)}/{len(rs)}"),
        ("Hidden tests passed, mean (range)", lambda rs: f"{mean([r['hidden_tests_passed'] for r in rs]):.1f}/{n_hidden} ({rng([r['hidden_tests_passed'] for r in rs])})"),
        ("Tasks marked done but failing (total)", lambda rs: f"{sum(len(r['false_done']) for r in rs)}"),
        ("Tasks left in progress or todo at end (total)", lambda rs: f"{sum(len(r['left_in_progress']) + len(r['left_todo']) for r in rs)}"),
        ("Cost per run, USD, mean (range)", lambda rs: f"{mean([r['cost_usd'] for r in rs]):.2f} ({rng([r['cost_usd'] for r in rs], '{:.2f}')})"),
        ("Wall-clock per run, s, mean (range)", lambda rs: f"{mean([r['wall_seconds'] for r in rs]):.0f} ({rng([r['wall_seconds'] for r in rs])})"),
        ("Agent turns per run, mean (range)", lambda rs: f"{mean([r['turns'] for r in rs]):.0f} ({rng([r['turns'] for r in rs])})"),
        ("Expired claims released by lease (total)", lambda rs: f"{sum(r.get('lease_releases', 0) for r in rs)}"),
        ("Test files edited (runs)", lambda rs: f"{sum(bool(r['test_files_edited']) for r in rs)}/{len(rs)}"),
        ("Permission denials (total)", lambda rs: f"{sum(r['permission_denials'] for r in rs)}"),
        ("Timed-out or errored agents (total)", lambda rs: f"{sum(len(r['timed_out']) + len(r['agent_errors']) for r in rs)}"),
    ]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(by_cond[c]) for c in CONDITIONS) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="shop", help="directory name under eval/projects/")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--agents", type=int, default=3)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--budget", type=float, default=4.0, help="max USD per agent session")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per run")
    ap.add_argument("--restart-turns", type=int, default=0,
                    help="stop a first wave of agents after this many turns each, then start a fresh wave")
    ap.add_argument("--restart-silent", action="store_true",
                    help="with --restart-turns, do not tell the second wave that the first was stopped")
    ap.add_argument("--lease", type=float, default=None,
                    help="claim lease in seconds for the agentspec condition (added to the spec's @meta)")
    ap.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS),
                    help="which conditions to run (default: both)")
    ap.add_argument("--first-run", type=int, default=1, help="index of the first run (to redo or extend a series)")
    ap.add_argument("--parallel-runs", type=int, default=2)
    ap.add_argument("--label", default="pilot")
    ap.add_argument("--workdir", type=Path, default=Path(tempfile.gettempdir()) / "agentspec-eval-runs",
                    help="where run directories go; must be outside any git repository")
    ap.add_argument("--results", type=Path, default=EVAL_DIR / "results")
    args = ap.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)
    args.results.mkdir(parents=True, exist_ok=True)
    # Agents see the git status of the repository they run in. Inside this repo that
    # exposes the hidden tests and reference solutions, so run directories must live elsewhere.
    in_repo = subprocess.run(["git", "-C", str(args.workdir), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True)
    if in_repo.returncode == 0:
        sys.exit(f"--workdir {args.workdir} is inside the git repository {in_repo.stdout.strip()}; "
                 "use a directory outside any repository.")
    project = Project.load(args.project)

    jobs = [(c, i) for i in range(args.first_run, args.first_run + args.runs) for c in args.conditions]
    with ThreadPoolExecutor(max_workers=args.parallel_runs) as pool:
        results = [r for r in pool.map(lambda job: do_run(job[0], job[1], project, args), jobs) if r]
    if not results:
        sys.exit("No valid runs.")

    table = summarize(results)
    (args.results / f"{args.label}-summary.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)


if __name__ == "__main__":
    main()
