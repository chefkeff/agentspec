"""
A/B harness: several Claude Code agents build the same project in a shared
directory, coordinating either through agentspec or through a plain shared
checklist. Each run is graded by hidden acceptance tests the agents never see.

    eval/.venv/bin/python eval/run_ab.py --runs 1
    eval/.venv/bin/python eval/run_ab.py --runs 5 --label full
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from agentspec import parse_spec, to_markdown  # noqa: E402
from agentspec.models import TaskStatus  # noqa: E402

SPEC_PATH = EVAL_DIR / "spec" / "shop.aspec"
VENV_BIN = EVAL_DIR / ".venv" / "bin"
CONDITIONS = ("agentspec", "checklist")
WORK_TASKS = ["T2", "T3", "T4", "T5", "T6", "T7", "T8"]
HIDDEN_FILE_TO_TASK = {
    "test_t2_inventory": "T2", "test_t3_pricing": "T3", "test_t4_tax": "T4",
    "test_t5_reservations": "T5", "test_t6_checkout": "T6", "test_t7_receipt": "T7",
    "test_t8_report": "T8",
}

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


def setup_run(run_dir: Path, condition: str) -> None:
    shutil.copytree(EVAL_DIR / "project", run_dir)
    shutil.copy(EVAL_DIR / "protocols" / f"{condition}.md", run_dir / "PROTOCOL.md")
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    if condition == "agentspec":
        (run_dir / "project.aspec").write_text(spec_text, encoding="utf-8")
    else:
        doc = parse_spec(spec_text)
        (run_dir / "PLAN.md").write_text(to_markdown(doc), encoding="utf-8")
        todo = ["# TODO", ""] + [
            f"- [{'x' if t.status == TaskStatus.DONE else ' '}] {t.id}: {t.title}" for t in doc.tasks
        ]
        (run_dir / "TODO.md").write_text("\n".join(todo) + "\n", encoding="utf-8")


def launch_agents(run_dir: Path, n_agents: int, model: str, budget: float, timeout: int) -> dict:
    env = dict(os.environ, PATH=f"{VENV_BIN}{os.pathsep}{os.environ['PATH']}")
    procs = []
    start = time.time()
    for k in range(1, n_agents + 1):
        name = f"agent-{k}"
        log = open(run_dir.parent / f"{run_dir.name}.{name}.jsonl", "w")
        cmd = [
            "claude", "-p", WORKER_PROMPT.format(name=name, n=n_agents),
            "--model", model,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk",
            "--allowedTools", *ALLOWED_TOOLS,
            "--strict-mcp-config", "--setting-sources", "project",
            "--no-session-persistence",
            "--max-budget-usd", str(budget),
        ]
        procs.append((name, subprocess.Popen(cmd, cwd=run_dir, env=env, stdout=log,
                                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL), log))

    timed_out = []
    for name, proc, log in procs:
        remaining = max(1, timeout - (time.time() - start))
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out.append(name)
        log.close()
    return {"wall_seconds": round(time.time() - start, 1), "timed_out": timed_out}


def parse_agent_log(path: Path) -> dict:
    stats = {"cost_usd": 0.0, "turns": 0, "is_error": None, "edited_files": [], "denials": 0,
             "result": None, "input_tokens": 0, "output_tokens": 0}
    edited = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
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
                denials=len(ev.get("permission_denials") or []),
                result=(ev.get("result") or "")[:300],
                input_tokens=(usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                              + usage.get("cache_creation_input_tokens", 0)),
                output_tokens=usage.get("output_tokens", 0),
            )
    stats["edited_files"] = edited
    return stats


def run_hidden_tests(run_dir: Path) -> dict:
    junit = run_dir.parent / f"{run_dir.name}.hidden.xml"
    env = dict(os.environ, SHOP_ROOT=str(run_dir))
    subprocess.run(
        [str(VENV_BIN / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
         f"--junitxml={junit}", str(EVAL_DIR / "hidden")],
        env=env, capture_output=True, text=True, timeout=300,
    )
    per_task = {t: {"passed": 0, "total": 0} for t in WORK_TASKS}
    if junit.exists():
        root = ET.parse(junit).getroot()
        for case in root.iter("testcase"):
            module = case.get("classname", "").split(".")[-1]
            task = HIDDEN_FILE_TO_TASK.get(module)
            if not task:
                continue
            per_task[task]["total"] += 1
            if not any(child.tag in ("failure", "error", "skipped") for child in case):
                per_task[task]["passed"] += 1
        # A module that fails to import shows up as a single collection error
        for case in root.iter("testcase"):
            if case.get("classname", "") == "" and any(c.tag == "error" for c in case):
                name = case.get("name", "")
                for module, task in HIDDEN_FILE_TO_TASK.items():
                    if module in name and per_task[task]["total"] == 0:
                        per_task[task]["total"] = 1
    return per_task


def marked_done(run_dir: Path, condition: str) -> list:
    if condition == "agentspec":
        spec = run_dir / "project.aspec"
        try:
            doc = parse_spec(spec.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [t.id for t in doc.tasks if t.status == TaskStatus.DONE and t.id in WORK_TASKS]
    todo = (run_dir / "TODO.md").read_text(encoding="utf-8")
    return [t for t in WORK_TASKS if re.search(rf"^\s*-\s*\[[xX]\]\s*{t}\b", todo, re.M)]


def score_run(run_dir: Path, condition: str, launch: dict, n_agents: int) -> dict:
    agents = {f"agent-{k}": parse_agent_log(run_dir.parent / f"{run_dir.name}.agent-{k}.jsonl")
              for k in range(1, n_agents + 1)}
    hidden = run_hidden_tests(run_dir)
    tasks_passing = [t for t, r in hidden.items() if r["total"] and r["passed"] == r["total"]]
    done = marked_done(run_dir, condition)

    def rel(fp):
        try:
            return str(Path(fp).resolve().relative_to(run_dir.resolve()))
        except ValueError:
            return fp

    edits_by_file = {}
    for name, a in agents.items():
        for fp in {rel(f) for f in a["edited_files"]}:
            edits_by_file.setdefault(fp, []).append(name)

    return {
        "condition": condition,
        "run": run_dir.name,
        "wall_seconds": launch["wall_seconds"],
        "timed_out": launch["timed_out"],
        "cost_usd": round(sum(a["cost_usd"] for a in agents.values()), 3),
        "turns": sum(a["turns"] for a in agents.values()),
        "input_tokens": sum(a["input_tokens"] for a in agents.values()),
        "output_tokens": sum(a["output_tokens"] for a in agents.values()),
        "hidden_tests_passed": sum(r["passed"] for r in hidden.values()),
        "hidden_tests_total": sum(r["total"] for r in hidden.values()),
        "tasks_passing": sorted(tasks_passing),
        "all_tasks_pass": len(tasks_passing) == len(WORK_TASKS),
        "marked_done": done,
        "false_done": sorted(set(done) - set(tasks_passing)),
        "src_files_edited_by_multiple_agents": {f: a for f, a in edits_by_file.items()
                                                if f.startswith("src/") and len(a) > 1},
        "test_files_edited": sorted(f for f in edits_by_file if f.startswith("tests/")),
        "state_file_hand_edits": sorted(f for f in edits_by_file if f in ("project.aspec",))
        if condition == "agentspec" else [],
        "permission_denials": sum(a["denials"] for a in agents.values()),
        "agent_errors": [n for n, a in agents.items() if a["is_error"] or a["is_error"] is None],
        "hidden_per_task": hidden,
    }


def do_run(condition: str, index: int, args) -> dict:
    run_dir = args.workdir / f"{args.label}-{condition}-{index}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    setup_run(run_dir, condition)
    print(f"[start] {run_dir.name}", flush=True)
    launch = launch_agents(run_dir, args.agents, args.model, args.budget, args.timeout)
    result = score_run(run_dir, condition, launch, args.agents)
    (args.results / f"{run_dir.name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[done]  {run_dir.name}: {result['hidden_tests_passed']}/{result['hidden_tests_total']} hidden tests, "
          f"{len(result['tasks_passing'])}/7 tasks, ${result['cost_usd']}, {result['wall_seconds']}s", flush=True)
    return result


def summarize(results: list) -> str:
    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    lines = ["| Metric | " + " | ".join(CONDITIONS) + " |", "| :--- | " + " | ".join("---:" for _ in CONDITIONS) + " |"]
    by_cond = {c: [r for r in results if r["condition"] == c] for c in CONDITIONS}
    rows = [
        ("Runs", lambda rs: f"{len(rs)}"),
        ("All 7 tasks pass (runs)", lambda rs: f"{sum(r['all_tasks_pass'] for r in rs)}/{len(rs)}"),
        ("Hidden tests passed (mean)", lambda rs: f"{mean([r['hidden_tests_passed'] for r in rs]):.1f}/31"),
        ("Hidden tests passed (min–max)", lambda rs: f"{min((r['hidden_tests_passed'] for r in rs), default=0)}–{max((r['hidden_tests_passed'] for r in rs), default=0)}"),
        ("Tasks marked done but failing (total)", lambda rs: f"{sum(len(r['false_done']) for r in rs)}"),
        ("Cost per run, USD (mean)", lambda rs: f"{mean([r['cost_usd'] for r in rs]):.2f}"),
        ("Wall-clock per run, s (mean)", lambda rs: f"{mean([r['wall_seconds'] for r in rs]):.0f}"),
        ("Agent turns per run (mean)", lambda rs: f"{mean([r['turns'] for r in rs]):.0f}"),
        ("Runs with a src file edited by 2+ agents", lambda rs: f"{sum(bool(r['src_files_edited_by_multiple_agents']) for r in rs)}/{len(rs)}"),
        ("Test files edited (runs)", lambda rs: f"{sum(bool(r['test_files_edited']) for r in rs)}/{len(rs)}"),
        ("Permission denials (total)", lambda rs: f"{sum(r['permission_denials'] for r in rs)}"),
        ("Timed-out or errored agents (total)", lambda rs: f"{sum(len(r['timed_out']) + len(r['agent_errors']) for r in rs)}"),
    ]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(by_cond[c]) for c in CONDITIONS) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--agents", type=int, default=3)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--budget", type=float, default=4.0, help="max USD per agent session")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per run")
    ap.add_argument("--parallel-runs", type=int, default=2)
    ap.add_argument("--label", default="pilot")
    ap.add_argument("--workdir", type=Path, default=EVAL_DIR / "runs")
    ap.add_argument("--results", type=Path, default=EVAL_DIR / "results")
    args = ap.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)
    args.results.mkdir(parents=True, exist_ok=True)

    jobs = [(c, i) for i in range(1, args.runs + 1) for c in CONDITIONS]
    with ThreadPoolExecutor(max_workers=args.parallel_runs) as pool:
        results = list(pool.map(lambda job: do_run(job[0], job[1], args), jobs))

    table = summarize(results)
    (args.results / f"{args.label}-summary.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)


if __name__ == "__main__":
    main()
