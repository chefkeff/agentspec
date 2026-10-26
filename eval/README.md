# A/B eval: agentspec vs. a plain shared checklist

Several Claude Code agents build the same small Python project (`shop`) at the same time in one shared directory. The only thing that differs between the two conditions is how they coordinate:

| Condition | Plan | Task state | Coordination |
| :--- | :--- | :--- | :--- |
| `agentspec` | `project.aspec` | `project.aspec`, changed only via the `aspec` CLI | `ready`, guarded claims, `pack`, `test`, `patch --verify` |
| `checklist` | `PLAN.md` (rendered from the same spec, with files and test commands) | `TODO.md` | Agents edit the checklist by hand |

Both get the same contracts, rules, task graph, file lists and test commands, the same worker prompt, model, tools and budget. See [protocols/](protocols/).

## The project

[spec/shop.aspec](spec/shop.aspec) has 7 open tasks (T2–T8). Four can start immediately; T2 and T3 both edit `src/shop/errors.py`, and T2 → T5 → T6 → T8 is a dependency chain. [project/](project/) is the starting point, with a light visible test per task for the agents' own checks.

## Grading

[hidden/](hidden/) holds 31 stricter acceptance tests, one file per task, which agents never see. [reference/](reference/) is a solution that passes all of them, which proves the tests are consistent with the spec.

Per run, the harness records hidden tests passed, tasks fully passing, tasks marked done but failing, cost, wall-clock time, turns, files edited by more than one agent, edits to tests, and permission denials.

## Results (2026-10-26, 5 runs per condition, 3 Sonnet agents)

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

## Running

```bash
python3 -m venv eval/.venv
eval/.venv/bin/pip install -e . pytest
eval/.venv/bin/python eval/run_ab.py --runs 1 --label pilot
eval/.venv/bin/python eval/run_ab.py --runs 5 --label full
```

Options: `--agents` (default 3), `--model` (default `sonnet`), `--budget` per agent in USD (default 4), `--timeout` per run in seconds (default 1800), `--parallel-runs` (default 2).

Agents run with `claude -p` in `dontAsk` permission mode and may only use Read, Edit, Write, Glob, Grep and `python3`, `aspec`, `sleep`, `ls` and `cat` in Bash. Run directories and agent logs go to `eval/runs/` (git-ignored); per-run results and a summary table go to `eval/results/`.
