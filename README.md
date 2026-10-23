# agentspec (`aspec`) v0.3

**agentspec** is a token-dense, BPE-optimized specification and task-DAG framework designed specifically for AI agent-to-agent memory, multi-agent swarm orchestration, and state persistence, with on-demand deterministic compilation into human-readable Markdown and Mermaid diagrams.

Instead of having LLM agents exchange verbose Markdown files that bloat context windows, agentspec stores project state in a computable AST that saves **40%–80% tokens** per turn, enforces DAG causal prerequisites, prevents file-write conflicts across parallel subagents, and guards execution with test verification gates.

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
[>] T2: implement AuthService token generation [after: T1] [ref: AuthService, Token] [touch: src/auth.py] [test: pytest tests/test_auth.py]
[ ] T3: integrate redis rate limiter [after: T2] [ref: AuthService] [touch: src/limiter.py]
[ ] T4: audit log streaming [after: T1] [touch: src/audit.py]
```

---

## Installation & Setup

```bash
cd agentspec
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## CLI Capabilities

### 1. Selective Subagent Context Packing & Deep Pruning (`pack`)
Generates the minimal causal dependency slice for a specific task. Prunes unneeded downstream tasks AND removes unreferenced types and services (`[ref: ...]`) to maximize token savings:
```bash
aspec pack examples/project.aspec --task T3
```
*Outputs an isolated prompt containing only the contracts and prerequisite tasks needed for `T3`.*

### 2. Multi-Agent Parallel Swarm Dispatcher (`ready`)
Computes execution readiness and uses graph coloring on declared `[touch: ...]` file locks to group ready tasks into conflict-free parallel execution tiers:
```bash
aspec ready examples/swarm.aspec
# Output JSON directly for orchestrator agents:
aspec ready examples/swarm.aspec --json
```

### 3. Automated Verification Gates (`test` & `patch --verify`)
Blocks tasks from transitioning to `done` if their configured acceptance test fails:
```bash
# Run verification gates directly:
aspec test examples/swarm.aspec --task T2

# Or enforce test gate during state mutation:
aspec patch examples/swarm.aspec --set T2=done --verify
```

### 4. In-Place State & Task Patching (`patch`)
Allows agents to update task states or append new tasks deterministically without rewriting the entire file:
```bash
aspec patch examples/project.aspec --set T3=done --set T4=in_progress
aspec patch examples/project.aspec --add-task "T7: deploy to staging [after: T6] [touch: deploy.sh]"
```

### 3. Workflow Linting & State Guards (`lint`)
Validates that downstream tasks are not started before prerequisites are complete, and detects orphan tasks and dead types:
```bash
aspec lint examples/project.aspec
```

### 4. Interactive Standalone Dashboard (`view`)
Generates a dark-mode HTML dashboard featuring interactive Mermaid dependency graphs, task status trackers, token density metrics, and a one-click "Copy Subagent Prompt" tool:
```bash
aspec view examples/project.aspec --out dashboard.html
```

### 5. Codebase Auto-Ingestion (`ingest`)
Scans existing Python codebases and auto-extracts `@dataclass`/type definitions and service methods into a starter `.aspec` file:
```bash
aspec ingest /path/to/my_python_project --out my_project.aspec
```

### 6. Token Savings Benchmark (`benchmark`)
Measures exact token counts against Markdown using `tiktoken`:
```bash
aspec benchmark examples/project.aspec
```

### 7. Markdown & Mermaid Transpilation (`render`)
```bash
aspec render examples/project.aspec --out spec.md
```

---

## Feature Comparison

| Capability | Markdown Prose | JSON Schemas | agentspec (`.aspec`) |
| :--- | :--- | :--- | :--- |
| **Token Cost (Full Spec)** | High (~600+ tok) | Medium (~450 tok) | **Low (~340 tok, 42% savings)** |
| **Subagent Task Slice** | Manual / Verbose | Complex JSON queries | **Native (`aspec pack`, 70%+ savings)** |
| **State Mutations** | Prone to syntax drift | JSON patch | **Zero-rewrite (`aspec patch`)** |
| **Workflow Integrity** | None | Schema only | **State guard & DAG cycle detection** |
| **Codebase Ingestion** | N/A | Custom scripts | **One-command (`aspec ingest`)** |
| **Human Visualization** | Native Markdown | Clunky | **Interactive Dashboard + Mermaid** |
