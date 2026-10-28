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

## Results: shop-xl (2026-10-27, 3 runs per condition, 6 Sonnet agents, `next` protocol)

| Metric | agentspec | checklist |
| :--- | ---: | ---: |
| All 13 tasks pass | 3/3 | 3/3 |
| Hidden tests passed | 59/59 every run | 59/59 every run |
| Tasks marked done but failing | 0 | 0 |
| Cost per run, USD (mean, range) | 1.48 (1.41–1.52) | 3.23 (3.03–3.44) |
| Wall-clock per run, s (mean, range) | 167 (151–180) | 210 (190–242) |
| Agent turns per run (mean, range) | 115 (107–120) | 223 (204–234) |

- **Quality: no difference.** Both conditions solved everything in every run.
- **Cost: agentspec about 54% cheaper** (the checklist costs 2.2×). Every agentspec run was cheaper, faster and used fewer turns than every checklist run. With 3 runs per condition the smallest possible two-sided Mann–Whitney p-value is 0.10, which is what all three measures reach.
- **Time: about 20% faster; turns: about half.**
- **Why:** across the 3 runs, checklist agents made 300 reads, 108 edits to `TODO.md` that failed because another agent had changed it first, and 56 `sleep` calls. agentspec agents made 62 `aspec next` calls and no `sleep` calls: `next --wait` replaced polling entirely. The scope check never fired, because no agent edited files outside its task.
- **Validity:** every run ran outside the repository and none touched it; no API errors, timeouts or test edits.
- **Caveats:** the agentspec condition here includes `aspec next`, so it is not directly comparable with the shop results above, which used the earlier ready/claim loop. Three runs per condition is a small sample, though the two conditions did not overlap on any cost measure.

The first shop-xl pilots were discarded. Their run directories were inside this repository, and Claude Code shows agents the repository's git status, which listed the paths of the other eval projects. Agents in both conditions followed those paths, read the shop project's hidden tests and wrote files into its starting template (since restored). The harness now puts run directories in the system temp directory, refuses a `--workdir` inside a git repository, and marks a run invalid if any agent touches the repository. Re-checked with that rule, all 12 shop runs above are clean.

> **Protocol versions:** the shop results used the earlier agentspec protocol (`ready`, then claim with `patch`, then `pack`). The shop-xl results and [protocols/agentspec.md](protocols/agentspec.md) use `aspec next --wait`, which claims and returns the next task in one call, with `--verify` also checking file scope.

## Results: shop-xl silent restart (2026-10-28, 3 runs per condition, 6 + 6 Sonnet agents, claim leases)

This scenario tests agentspec 0.4's claim leases. A first wave of 6 agents is cut off after 12 turns each, which leaves tasks claimed and files half-written. A second wave of 6 agents then starts **without being told** that anyone was stopped. In the agentspec condition, abandoned claims can only come back through leases, set to 180 seconds for this eval (`--lease 180`; the default is 30 minutes). In the checklist condition, nothing releases a `[~]` claim unless an agent decides to.

| Metric | agentspec | checklist |
| :--- | ---: | ---: |
| Runs | 3 | 3 |
| All 13 tasks pass (runs) | 3/3 | 3/3 |
| Hidden tests passed, mean (range) | 59.0/59 (59–59) | 59.0/59 (59–59) |
| Tasks marked done but failing (total) | 0 | 0 |
| Tasks left in progress or todo at end (total) | 0 | 0 |
| Cost per run, USD, mean (range) | 2.50 (1.96–3.55) | 4.61 (4.29–5.04) |
| Wall-clock per run, s, mean (range) | 621 (346–942) | 513 (476–566) |
| Agent turns per run, mean (range) | 183 (129–269) | 287 (279–300) |
| Expired claims released by lease (total) | 10 | 0 |
| Test files edited (runs) | 0/3 | 0/3 |
| Permission denials (total) | 1 | 0 |
| Timed-out or errored agents (total) | 0 | 0 |

What happened:

- **Both conditions recovered every abandoned task**, and every run passed all 59 hidden tests.
- **agentspec did it within its protocol.** `next` released 10 expired claims across the 3 runs and handed those tasks to second-wave agents. No `done@owner` patch was rejected and no scope check fired.
- **The checklist agents recovered by breaking their protocol.** Second-wave agents noticed that tasks had been `[~]` for a long time, ran their tests, and then marked other agents' tasks done or claimed tasks whose prerequisites were still `[~]` ("T2, T3, T4 are stuck but their tests all pass ... I'll claim T5"). It worked here because the abandoned code happened to pass. Nothing would have stopped them marking half-finished work as done.
- **agentspec cost 46% less** ($2.50 vs $4.61 per run) **but was slower** (621 s vs 513 s). Its second wave has to wait for leases to run out (up to 3 minutes), while checklist agents took stuck tasks over as soon as they suspected them.
- **Run agentspec-3 cost $3.55** because one agent (agent-10) called `aspec next` without `--wait` 110 times in a tight loop while waiting for leases, against 1–8 calls for every other agent. `next` said "run the same command again" when no task was ready, which did not tell an agent how long to wait. It now reports how long until the earliest claim's lease runs out and, when called without `--wait`, tells the agent to use it instead of polling.

The first attempt at run 3 of both conditions was discarded: the machine went to sleep mid-run, cutting off the second wave (both runs reported 6,864 s and 47,777 s of wall-clock time against an 1,800 s cap). The harness now marks a run invalid if it overruns its cap by more than 5 minutes, and the replacement runs were made under `caffeinate -i` with `--first-run 3`.

## Running

```bash
python3 -m venv eval/.venv
eval/.venv/bin/pip install -e . pytest
eval/.venv/bin/python eval/run_ab.py --runs 5 --label full
eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --runs 4 --label xl
eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --runs 4 --restart-turns 12 --label xl-restart
caffeinate -i eval/.venv/bin/python eval/run_ab.py --project shop-xl --agents 6 --runs 3 --restart-turns 12 \
    --restart-silent --lease 180 --label xl-restart-silent
```

`--restart-turns N` cuts a first wave of agents off after N turns each, which leaves tasks half-claimed and files half-written, then starts a fresh wave that is told the earlier agents were stopped. With `--restart-silent` the fresh wave is not told. `--lease S` adds a claim lease of S seconds to the agentspec spec's `@meta`.

Options: `--project` (default `shop`), `--agents` (default 3), `--model` (default `sonnet`), `--budget` per agent in USD (default 4), `--timeout` per run in seconds (default 1800), `--parallel-runs` (default 2), `--first-run` (index of the first run, to redo or extend a series). On a laptop, run under `caffeinate -i` so the machine doesn't sleep mid-run.

Agents run with `claude -p` in `dontAsk` permission mode and may only use Read, Edit, Write, Glob, Grep and `python3`, `aspec`, `sleep`, `ls` and `cat` in Bash. Run directories and agent logs go to `$TMPDIR/agentspec-eval-runs/` by default (`--workdir`, which must be outside any git repository); per-run results and a summary table go to `eval/results/`. A run is discarded, and the batch stops, if any agent hits an API error such as a usage limit or touches files in this repository.
