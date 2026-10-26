# agentspec (`aspec`) v0.3

**agentspec** is a token-dense specification and task-DAG framework for AI agent-to-agent memory, multi-agent swarm orchestration, and state persistence, with on-demand deterministic compilation into human-readable Markdown and Mermaid diagrams.

Instead of having LLM agents exchange verbose Markdown files that bloat context windows, agentspec stores project state in a parsed, computable spec that:

- saves **40%–80% tokens** per turn compared to equivalent Markdown,
- enforces DAG prerequisites, so tasks can't be claimed or completed out of order,
- hands each agent its next task in one atomic step (`aspec next`), so agents never claim the same work,
- prevents file-write conflicts between parallel subagents through declared file locks,
- checks that a finished task only changed the files it declared,
- serializes concurrent edits to the spec, so simultaneous agents never lose each other's updates,
- guards completion with test verification gates.

In an [A/B evaluation](eval/README.md) against agents coordinating through a shared Markdown checklist, agentspec runs cost about 19% less with the same results.

---

## The Syntax at a Glance

```text
@spec 0.3
@meta app: "auth-gateway" | stack: "fastapi+redis"

# 1. ARCHITECTURAL CONTRACTS
!type Token = { id: str, perms: str[], exp: int }
!svc AuthService:
  login(u: str, p: str) -> Token
  verify(token: str) -> bool

# 2. RATIONALES & INVARIANTS (The "Why")
!why auth: "stateless JWT to allow horizontal scaling behind Traefik"
!rule sec: "never persist raw passwords; bcrypt work factor >= 12"

# 3. TASK DAG (The "Where") with Parallel File Locks & Verification Gates
[x] T1: initialize fastapi skeleton [touch: src/app.py]
[>] T2: implement AuthService token generation [after: T1] [ref: AuthService, Token] [touch: src/auth.py] [test: pytest tests/test_auth.py] [by: agent-a]
[ ] T3: integrate redis rate limiter [after: T2] [ref: AuthService] [touch: src/limiter.py]
[ ] T4: audit log streaming [after: T1] [touch: src/audit.py]
```

| Primitive | Meaning |
| :--- | :--- |
| `@spec`, `@meta` | Spec version and runtime metadata |
| `!type`, `!svc` | Typed domain models and service signatures |
| `!why`, `!rule`, `!invariant` | Architectural rationale, hard constraints, domain truths |
| `[ ]`, `[>]`, `[x]` | Task status: todo, in progress, done |

### Task tags

| Tag | Meaning |
| :--- | :--- |
| `[after: T1, T2]` | Prerequisites that must be done before the task can be claimed or completed |
| `[ref: AuthService, Token]` | Contracts the task uses (drives pruning in `aspec pack`) |
| `[touch: src/a.py, src/models/, src/*.py]` | File locks: the only files the task may modify (exact paths, directories or glob patterns, relative to the spec's directory). Checked by `patch --verify`. A task **without** `[touch: ...]` has an undeclared scope and is treated as conflicting with every other task |
| `[test: pytest tests/x.py]` | Acceptance gate run by `aspec test` and `aspec patch --verify` |
| `[by: agent-a]` | Owner of an in-progress task, set when claiming with `T2=in_progress@agent-a` |

---

## Installation & Setup

```bash
git clone https://github.com/chefkeff/agentspec.git
cd agentspec
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Python 3.9+. Dependencies: `tiktoken`, `rich`.

---

## CLI Reference

| Command | Purpose |
| :--- | :--- |
| `aspec init [file]` | Create a starter `.aspec` template (default `project.aspec`) |
| `aspec check <file>` | Parse the spec and validate the task DAG (missing deps, cycles) |
| `aspec lint <file>` | Workflow hygiene: out-of-order states, orphan tasks, unused types, empty services |
| `aspec next <file> --as NAME [--wait]` | Atomically claim the next ready task and print its scoped prompt |
| `aspec ready <file> [--json]` | Ready tasks, lock waits and conflict-free parallel batches |
| `aspec pack <file> -t T3` | Minimal subagent prompt for one task |
| `aspec patch <file> ...` | Claim, complete (with scope and test checks), release and add tasks; add rationale and rules |
| `aspec test <file> [-t T2]` | Run `[test: ...]` verification gates |
| `aspec render <file> [-o out.md]` | Transpile to Markdown with a Mermaid DAG |
| `aspec view <file> [-o out.html]` | Standalone HTML dashboard |
| `aspec benchmark <file>` | Token counts vs. equivalent Markdown (`tiktoken`) |
| `aspec ingest [path] [-o out.aspec]` | Draft a spec from a Python codebase |
| `aspec compress <file.md> [-o out.aspec]` | Draft a dense spec from verbose Markdown |
| `aspec mcp` | Run the Model Context Protocol stdio server |

### 1. Claiming the Next Task (`next`)
The simplest way for an agent to get work. One call finds a ready task, claims it under the spec lock and prints its scoped prompt (the same slice as `pack`), plus the files it may edit and the command to finish it:

```bash
aspec next project.aspec --as agent-3
aspec next project.aspec --as agent-3 --wait --timeout 90   # block until a task is ready
aspec next project.aspec --as agent-3 --json                # structured output
```

- If the agent already holds an in-progress task, `next` returns that task again instead of claiming a second one.
- Tasks whose files are locked by another in-progress task are skipped.
- Outcomes: *claimed*, *resumed*, *all done*, or *none ready* (with `--wait`, it keeps polling until one of the others happens or the timeout passes; keep the timeout under your agent's shell-command limit).

### 2. Parallel Swarm Dispatcher (`ready`)
Lists tasks whose prerequisites are done and groups them into conflict-free parallel batches using their `[touch: ...]` file locks:

```bash
aspec ready examples/swarm.aspec
# Structured output for orchestrator agents:
aspec ready examples/swarm.aspec --json
```

- Tasks whose files are held by an **in-progress** task are not offered as ready. They are reported as *waiting on locks*, together with the tasks holding them (`waiting_on_locks` in JSON).
- Tasks without `[touch: ...]` are scheduled alone in their own batch.
- Everything in **Batch 1** can be dispatched to parallel subagents at once.

### 3. Claiming and Updating Tasks (`patch`)
Agents mutate state through `aspec patch` instead of rewriting the file:

```bash
# Claim a task, recording who owns it
aspec patch examples/swarm.aspec --set T2=in_progress@agent-a

# Complete it, checking its file scope and running its [test: ...] gate first
aspec patch examples/swarm.aspec --set T2=done --verify

# Release a claim without completing it
aspec patch examples/swarm.aspec --set T2=todo

# Add tasks, rationale and rules
aspec patch examples/swarm.aspec --add-task "T7: deploy to staging [after: T6] [touch: deploy.sh]"
aspec patch examples/swarm.aspec --add-why 'cache: "Redis sorted sets for sliding-window rate limiting"'
aspec patch examples/swarm.aspec --add-rule 'auth: "All endpoints require a verified token"'
```

Guards applied by `patch`:

- **Claiming** (`=in_progress`) is rejected if the task is already in progress (unless re-claimed by the same owner), already done, has unfinished prerequisites, or its `[touch: ...]` files overlap a task already in progress.
- **Completing** (`=done`) is rejected if any prerequisite is not done. With `--verify`, it is also rejected if the task changed files outside its `[touch: ...]` list (see [Scope Checking](#scope-checking)) or its `[test: ...]` gate fails.
- **Releasing** (`=todo`) clears the owner and frees the task's file locks.
- Multiple `--set` / `--add-*` flags apply in order, and the whole patch is rejected if any part fails, leaving the file unchanged.

### 4. Subagent Context Packing (`pack`)
Generates the minimal dependency slice for one task: its prerequisite chain, the contracts it references through `[ref: ...]` (followed transitively through types and services), and all rules and invariants. Unrelated tasks, types and services are pruned:

```bash
aspec pack examples/project.aspec --task T3
aspec pack examples/project.aspec --task T3 --raw        # bare .aspec slice, no prompt wrapper
aspec pack examples/project.aspec --task T3 --no-prune   # keep all contracts
```

### 5. Verification Gates (`test`)
```bash
aspec test examples/swarm.aspec --task T2   # one task
aspec test examples/swarm.aspec             # every task with a [test: ...] gate
```

> **Note:** `[test: ...]` commands run through the shell with your user's permissions. Review test commands added by agents before running gates.

### 6. Linting and Validation (`check`, `lint`)
```bash
aspec check examples/project.aspec   # parse + DAG integrity (missing deps, cycles)
aspec lint examples/project.aspec    # state guards, orphan tasks, unused types
```

### 7. Human-Readable Output (`render`, `view`)
```bash
aspec render examples/project.aspec --out spec.md
aspec view examples/project.aspec --out dashboard.html
```
`view` produces a dark-mode HTML dashboard with an interactive Mermaid dependency graph, task status tracker, token metrics and a "Copy Subagent Prompt" button.

### 8. Bootstrapping a Spec (`init`, `ingest`, `compress`)
```bash
aspec init project.aspec
aspec ingest /path/to/my_python_project --out my_project.aspec   # extracts classes and service methods
aspec compress verbose_plan.md --out plan.aspec                  # strips filler prose into a draft
```
`ingest` and `compress` produce drafts; review their output before relying on it.

### 9. Token Benchmark (`benchmark`)
```bash
aspec benchmark examples/project.aspec
```

---

## Scope Checking

When a task is claimed (with `next` or `patch --set T<id>=in_progress`), agentspec records a fingerprint of every project file under the spec's directory in `<spec>.claims/T<id>.json`. When the task is marked done with `--verify`, the project is compared against that snapshot:

- Changed, created or deleted files covered by the task's own `[touch: ...]` list are fine.
- So are files of other tasks that were in progress, or were started, while this task was held: those changes came from other agents.
- Anything else is rejected, naming the files, before the test gate runs. The agent must revert those changes or the plan must be updated to include the files.

Hidden files and directories, `__pycache__`, `node_modules` and the spec's own lock and claims files are ignored. Tasks without `[touch: ...]`, and tasks claimed before snapshots existed, are not checked. The snapshot is removed when the task is completed or released. Add `*.aspec.claims/` to your `.gitignore`.

## Concurrency Model

Several agents can safely run `aspec patch` and `aspec next` against the same spec at the same time:

1. Each patch or claim takes an exclusive lock on a sidecar file, `<spec>.lock` (add `*.aspec.lock` to `.gitignore`).
2. Under the lock, the spec is re-read, so the patch applies to the latest state rather than a stale copy.
3. The new spec is written to a temporary file and atomically renamed into place, so readers never see a half-written file.
4. `--verify` scope checks and test gates run **before** the lock is taken, so a slow test suite doesn't block other agents.

Combined with the claim guards, this means that when several agents race for the same task, exactly one gets it: the others get a clear rejection from `patch`, or a different task from `next`.

> **Note:** `patch` re-serializes the spec in canonical order, so `#` comments and custom section ordering are not preserved.

---

## MCP Server

`aspec mcp` runs a stdio [Model Context Protocol](https://modelcontextprotocol.io) server exposing:

| Tool | Purpose |
| :--- | :--- |
| `aspec_next` | Claim the next ready task for an `owner` (or return the one it holds), optionally waiting, and return its scoped prompt |
| `aspec_pack` | Subagent slice for a task |
| `aspec_patch` | Apply mutations (e.g. `T2=in_progress@agent-a`, `T2=done`, `+task T5: ...`), optional `verify` (scope check and test gate). Rejected patches are returned as `Patch rejected: <reason>` |
| `aspec_ready` | Ready tasks, owners, lock waits and parallel batches as JSON |
| `aspec_verify` | Run a task's `[test: ...]` gate |
| `aspec_lint` | Lint report |
| `aspec_render` | Markdown + Mermaid rendering |

Example Claude Code configuration (`.mcp.json`):

```json
{
  "mcpServers": {
    "agentspec": { "command": "aspec", "args": ["mcp"] }
  }
}
```

---

## Python API

```python
from pathlib import Path
from agentspec import parse_spec, patch_file, claim_next, get_task_schedule, format_subagent_prompt, PatchError

doc = parse_spec(Path("project.aspec").read_text())
schedule = get_task_schedule(doc)
for batch in schedule.parallel_batches:
    print(batch.batch_index, [t.id for t in batch.tasks])

result = claim_next(Path("project.aspec"), "agent-b", wait=True, timeout=60)
print(result.status, result.task.id if result.task else None)  # e.g. "claimed T3"

try:
    patch_file(Path("project.aspec"), ["T3=done"], verify=True)
except PatchError as e:
    print("not done yet:", e)  # out-of-scope changes or a failing test gate

print(format_subagent_prompt(doc, "T3"))
```

---

## Agent Workflow

Agents working in a repository managed by agentspec follow the loop in [AGENTS.md](AGENTS.md): get a task (`next --as <agent>`), modify only its `[touch: ...]` files, run its gate (`test`), then mark it done (`patch --set T<id>=done --verify`), and repeat until `next` reports that all tasks are done. Orchestrators delegate with `aspec pack` instead of passing full plans to subagents.

---

## Feature Comparison

| Capability | Markdown Prose | JSON Schemas | agentspec (`.aspec`) |
| :--- | :--- | :--- | :--- |
| **Token Cost (Full Spec)** | High (~600+ tok) | Medium (~450 tok) | **Low (~340 tok, 42% savings)** |
| **Subagent Task Slice** | Manual / Verbose | Complex JSON queries | **Native (`aspec pack`, 70%+ savings)** |
| **State Mutations** | Prone to syntax drift | JSON patch | **Locked, atomic `aspec patch`** |
| **Concurrent Agents** | Lost updates | Lost updates | **Atomic `next`, guarded claims + file locks** |
| **Scope Enforcement** | None | None | **`--verify` rejects out-of-scope changes** |
| **Workflow Integrity** | None | Schema only | **State guards & DAG cycle detection** |
| **Codebase Ingestion** | N/A | Custom scripts | **One-command (`aspec ingest`)** |
| **Human Visualization** | Native Markdown | Clunky | **Interactive Dashboard + Mermaid** |

---

## Examples

See [examples/README.md](examples/README.md) for reference specs, packed subagent slices, compression samples and rendered outputs.

## Development

```bash
pip install -e . pytest
pytest
```

The test suite includes multi-process tests that race concurrent patches and claims against the same spec file.

## License

MIT. See [LICENSE](LICENSE).
