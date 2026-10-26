# A/B eval: agentspec vs. a plain shared checklist

Several Claude Code agents build the same small Python project (`shop`) at the same time in one shared directory. The only thing that differs between the two conditions is how they coordinate:

| Condition | Plan | Task state | Coordination |
| :--- | :--- | :--- | :--- |
| `agentspec` | `project.aspec` | `project.aspec`, changed only via the `aspec` CLI | `ready`, guarded claims, `pack`, `test`, `patch --verify` |
| `checklist` | `PLAN.md` (rendered from the same spec, with files and test commands) | `TODO.md` | Agents edit the checklist by hand |

Both get the same contracts, rules, task graph, file lists and test commands, the same worker prompt, model, tools and budget. See [protocols/](protocols/).

## Projects

Each project in [projects/](projects/) has a `spec.aspec` (the single source for both conditions), a `project/` starting point with a light visible test per task, `hidden/` acceptance tests (one file per task, never shown to agents) and a `reference/` solution that passes every hidden test, which proves the tests match the spec.

| Project | Open tasks | Hidden tests | Shared files |
| :--- | ---: | ---: | :--- |
| [shop](projects/shop/) | 7 | 31 | `errors.py` (2 tasks) |
| [shop-xl](projects/shop-xl/) | 13 | 59 | `errors.py` (4 tasks), `pricing.py` (2), `api.py` (3) |

## Grading

Per run, the harness records hidden tests passed, tasks fully passing, tasks marked done but failing, cost, wall-clock time, turns, files edited by more than one agent, edits to tests, and permission denials.

## Results: shop (2026-10-26, 5 runs per condition, 3 Sonnet agents)

| Metric | agentspec | checklist |
| :--- | ---: | ---: |
| All 7 tasks pass | 5/5 | 5/5 |
| Hidden tests passed | 31/31 every run | 31/31 every run |
| Tasks marked done but failing | 0 | 0 |
| Cost per run, USD (mean, range) | 0.84 (0.72–0.93) | 1.04 (0.99–1.08) |
| Wall-clock per run, s (mean, range) | 124 (95–160) | 157 (136–176) |
| Agent turns per run (mean, range) | 69 (61–78) | 86 (83–88) |

- **Quality: no difference.** Both conditions solved everything in every run, so this project is too easy to show any quality effect.
- **Cost: agentspec about 19% cheaper.** Every agentspec run cost less than every checklist run (Mann–Whitney U = 0, p ≈ 0.008 two-sided). The same holds for turns.
- **Time: agentspec about 21% faster on average,** but the ranges overlap, so this is suggestive rather than conclusive.
- **Why:** checklist agents spend turns re-reading `TODO.md` and retrying edits after another agent changed it first. agentspec agents coordinate through one-line CLI calls, and refused claims are resolved in one step.
- **Caveats:** one small, precisely specified project; 5 runs per condition. The two "files edited by 2+ agents" cases are `errors.py`, which T2 and T3 legitimately share. The two permission denials were agents trying an `until ...; do sleep` polling loop, which the tool allowlist doesn't cover.

## shop-xl: no valid results yet

The first shop-xl pilots were discarded. Their run directories were inside this repository, and Claude Code shows agents the repository's git status, which listed the paths of the other eval projects. Agents in both conditions followed those paths, read the shop project's hidden tests and wrote files into its starting template (since restored). The harness now puts run directories in the system temp directory, refuses a `--workdir` inside a git repository, and marks a run invalid if any agent touches the repository. Re-checked with that rule, all 12 shop runs above are clean.

> **Protocol change:** the shop results above used the earlier agentspec protocol (`ready`, then claim with `patch`, then `pack`). [protocols/agentspec.md](protocols/agentspec.md) now uses `aspec next --wait`, which claims and returns the next task in one call, and `--verify` now also checks file scope. Rerun to measure the new flow.

## Running

```bash
python3 -m venv eval/.venv
eval/.venv/bin/pip install -e . pytest
eval/.venv/bin/python eval/run_ab.py --runs 5 --label full
eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --runs 4 --label xl
eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --runs 4 --restart-turns 12 --label xl-restart
```

`--restart-turns N` cuts a first wave of agents off after N turns each, which leaves tasks half-claimed and files half-written, then starts a fresh wave that is told the earlier agents were stopped.

Options: `--project` (default `shop`), `--agents` (default 3), `--model` (default `sonnet`), `--budget` per agent in USD (default 4), `--timeout` per run in seconds (default 1800), `--parallel-runs` (default 2).

Agents run with `claude -p` in `dontAsk` permission mode and may only use Read, Edit, Write, Glob, Grep and `python3`, `aspec`, `sleep`, `ls` and `cat` in Bash. Run directories and agent logs go to `$TMPDIR/agentspec-eval-runs/` by default (`--workdir`, which must be outside any git repository); per-run results and a summary table go to `eval/results/`. A run is discarded, and the batch stops, if any agent hits an API error such as a usage limit or touches files in this repository.
