# agentspec (`aspec`) v0.3

**agentspec** is a token-dense specification and task-DAG framework for AI agent-to-agent memory, multi-agent swarm orchestration, and state persistence, with on-demand deterministic compilation into human-readable Markdown and Mermaid diagrams.

Instead of having LLM agents exchange verbose Markdown files that bloat context windows, agentspec stores project state in a parsed, computable spec that:

- saves **40%–80% tokens** per turn compared to equivalent Markdown,
- enforces DAG prerequisites, so tasks can't be claimed or completed out of order,
- prevents file-write conflicts between parallel subagents through declared file locks,
- serializes concurrent edits to the spec, so simultaneous agents never lose each other's updates,
- guards completion with test verification gates.

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
| `[touch: src/a.py, src/b.py]` | File locks: the only files the task may modify. A task **without** `[touch: ...]` has an undeclared scope and is treated as conflicting with every other task |
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
| `aspec ready <file> [--json]` | Ready tasks, lock waits and conflict-free parallel batches |
| `aspec pack <file> -t T3` | Minimal subagent prompt for one task |
| `aspec patch <file> ...` | Claim, complete, release and add tasks; add rationale and rules |
| `aspec test <file> [-t T2]` | Run `[test: ...]` verification gates |
| `aspec render <file> [-o out.md]` | Transpile to Markdown with a Mermaid DAG |
| `aspec view <file> [-o out.html]` | Standalone HTML dashboard |
| `aspec benchmark <file>` | Token counts vs. equivalent Markdown (`tiktoken`) |
| `aspec ingest [path] [-o out.aspec]` | Draft a spec from a Python codebase |
| `aspec compress <file.md> [-o out.aspec]` | Draft a dense spec from verbose Markdown |
| `aspec mcp` | Run the Model Context Protocol stdio server |

### 1. Parallel Swarm Dispatcher (`ready`)
Lists tasks whose prerequisites are done and groups them into conflict-free parallel batches using their `[touch: ...]` file locks:

```bash
aspec ready examples/swarm.aspec
# Structured output for orchestrator agents:
aspec ready examples/swarm.aspec --json
```

- Tasks whose files are held by an **in-progress** task are not offered as ready. They are reported as *waiting on locks*, together with the tasks holding them (`waiting_on_locks` in JSON).
- Tasks without `[touch: ...]` are scheduled alone in their own batch.
- Everything in **Batch 1** can be dispatched to parallel subagents at once.

### 2. Claiming and Updating Tasks (`patch`)
Agents mutate state through `aspec patch` instead of rewriting the file:

```bash
# Claim a task, recording who owns it
aspec patch examples/swarm.aspec --set T2=in_progress@agent-a

# Complete it, running its [test: ...] gate first
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
- **Completing** (`=done`) is rejected if any prerequisite is not done. With `--verify`, a failing `[test: ...]` gate also rejects it.
- **Releasing** (`=todo`) clears the owner and frees the task's file locks.
- Multiple `--set` / `--add-*` flags apply in order, and the whole patch is rejected if any part fails, leaving the file unchanged.

### 3. Subagent Context Packing (`pack`)
Generates the minimal dependency slice for one task: its prerequisite chain, the contracts it references through `[ref: ...]` (followed transitively through types and services), and all rules and invariants. Unrelated tasks, types and services are pruned:

```bash
aspec pack examples/project.aspec --task T3
aspec pack examples/project.aspec --task T3 --raw        # bare .aspec slice, no prompt wrapper
aspec pack examples/project.aspec --task T3 --no-prune   # keep all contracts
```

### 4. Verification Gates (`test`)
```bash
aspec test examples/swarm.aspec --task T2   # one task
aspec test examples/swarm.aspec             # every task with a [test: ...] gate
```

> **Note:** `[test: ...]` commands run through the shell with your user's permissions. Review test commands added by agents before running gates.

### 5. Linting and Validation (`check`, `lint`)
```bash
aspec check examples/project.aspec   # parse + DAG integrity (missing deps, cycles)
aspec lint examples/project.aspec    # state guards, orphan tasks, unused types
```

### 6. Human-Readable Output (`render`, `view`)
```bash
aspec render examples/project.aspec --out spec.md
aspec view examples/project.aspec --out dashboard.html
```
`view` produces a dark-mode HTML dashboard with an interactive Mermaid dependency graph, task status tracker, token metrics and a "Copy Subagent Prompt" button.

### 7. Bootstrapping a Spec (`init`, `ingest`, `compress`)
```bash
aspec init project.aspec
aspec ingest /path/to/my_python_project --out my_project.aspec   # extracts classes and service methods
aspec compress verbose_plan.md --out plan.aspec                  # strips filler prose into a draft
```
`ingest` and `compress` produce drafts; review their output before relying on it.

### 8. Token Benchmark (`benchmark`)
```bash
aspec benchmark examples/project.aspec
```

---

## Concurrency Model

Several agents can safely run `aspec patch` against the same spec at the same time:

1. Each patch takes an exclusive lock on a sidecar file, `<spec>.lock` (ignored via `.gitignore`).
2. Under the lock, the spec is re-read, so the patch applies to the latest state rather than a stale copy.
3. The new spec is written to a temporary file and atomically renamed into place, so readers never see a half-written file.
4. `--verify` gates run **before** the lock is taken, so a slow test suite doesn't block other agents.

Combined with the claim guards, this means that when several agents race to claim the same task, exactly one succeeds and the others get a clear rejection.

> **Note:** `patch` re-serializes the spec in canonical order, so `#` comments and custom section ordering are not preserved.

---

## MCP Server

`aspec mcp` runs a stdio [Model Context Protocol](https://modelcontextprotocol.io) server exposing:

| Tool | Purpose |
| :--- | :--- |
| `aspec_pack` | Subagent slice for a task |
| `aspec_patch` | Apply mutations (e.g. `T2=in_progress@agent-a`, `T2=done`, `+task T5: ...`), optional `verify`. Rejected patches are returned as `Patch rejected: <reason>` |
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
from agentspec import parse_spec, patch_file, get_task_schedule, format_subagent_prompt, PatchError

doc = parse_spec(Path("project.aspec").read_text())
schedule = get_task_schedule(doc)
for batch in schedule.parallel_batches:
    print(batch.batch_index, [t.id for t in batch.tasks])

try:
    patch_file(Path("project.aspec"), ["T3=in_progress@agent-b"])
except PatchError as e:
    print("claim rejected:", e)

print(format_subagent_prompt(doc, "T3"))
```

---

## Agent Workflow

Agents working in a repository managed by agentspec follow the loop in [AGENTS.md](AGENTS.md): find ready tasks (`ready`), claim one (`patch --set T<id>=in_progress@<agent>`), modify only its `[touch: ...]` files, run its gate (`test`), then mark it done (`patch --set T<id>=done --verify`). Orchestrators delegate with `aspec pack` instead of passing full plans to subagents.

---

## Feature Comparison

| Capability | Markdown Prose | JSON Schemas | agentspec (`.aspec`) |
| :--- | :--- | :--- | :--- |
| **Token Cost (Full Spec)** | High (~600+ tok) | Medium (~450 tok) | **Low (~340 tok, 42% savings)** |
| **Subagent Task Slice** | Manual / Verbose | Complex JSON queries | **Native (`aspec pack`, 70%+ savings)** |
| **State Mutations** | Prone to syntax drift | JSON patch | **Locked, atomic `aspec patch`** |
| **Concurrent Agents** | Lost updates | Lost updates | **Guarded claims + file locks** |
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
