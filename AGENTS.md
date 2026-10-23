# AGENTS.md — Agent Operating Protocol for agentspec

Welcome, Agent. This codebase is managed by **agentspec (`aspec`)**, a deterministic specification and task-DAG framework designed specifically for AI agent-to-agent coordination, memory persistence, and token-dense state synchronization.

When operating in this repository, you **must** adhere strictly to the protocols, grammar, and mutation rules documented below.

---

## 1. Syntax & Semantics Quick Reference

An `.aspec` file defines three foundational layers:

| Syntax Primitive | Layer | Meaning for Agents |
| :--- | :--- | :--- |
| `@spec`, `@meta` | Environment | Spec version and runtime metadata (stack, framework, team). |
| `!why <id>: "<rationale>"` | Rationale | Architectural decisions. **Never reverse these decisions** unless explicitly instructed by the user. |
| `!rule <id>: "<constraint>"` | Security / Rules | Strict requirements (PCI, crypto, validation, auth). **Zero exceptions.** |
| `!invariant <id>: "<truth>"` | Domain Invariant | Immutable business truths (e.g., currency units, integer cents, timestamp formats). |
| `!type <Name> = { ... }` | Schema | Typed domain models and schemas. Mirror these exact types in your code. |
| `!svc <Name>:` | Service Interface | Service method signatures and expected return/error types. |
| `[ ]`, `[>]`, `[x]` | Execution DAG | Task states: `[ ]` (TODO), `[>]` (IN_PROGRESS), `[x]` (DONE). |

### Task Bracketed Tags
* `[after: T1, T2]` — Prerequisites: You must not start this task until listed tasks are `[x] done`.
* `[ref: CartService, Order]` — Domain Scope: This task only touches the specified services and types.
* `[touch: src/cart.py, tests/test_cart.py]` — File Locks: You are **only permitted to modify these files** during this task.
* `[test: pytest tests/test_cart.py]` — Acceptance Gate: Verification command that must pass before marking task done.

---

## 2. The Standard Agent Execution Loop

Whenever you are assigned to implement features or advance the project, follow this 5-step lifecycle:

```
                  ┌──────────────────────┐
                  │ 1. Find Ready Tasks  │  aspec ready <file> [--json]
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 2. Claim & Lock Task │  aspec patch <file> --set T<id>=in_progress
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 3. Implement Feature │  Modify strictly within [touch: ...] files
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 4. Run Test Gate     │  aspec test <file> -t T<id>
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 5. Mark Complete     │  aspec patch <file> --set T<id>=done --verify
                  └──────────────────────┘
```

### Step 1: Discover Unblocked Work
Inspect the project DAG to see which tasks are ready for execution:
```bash
aspec ready project.aspec
# Or obtain structured JSON for orchestrator parsing:
aspec ready project.aspec --json
```
* Select a task from **Batch 1**. Tasks in Batch 1 have all prerequisites satisfied and disjoint file locks, meaning they can be worked on concurrently without git merge collisions.

### Step 2: Claim the Task
Before writing code, transition the task into progress to signal other agents and developers:
```bash
aspec patch project.aspec --set T<id>=in_progress
```

### Step 3: Implement Within Scope
* **File Scoping**: Modify *only* the files declared in `[touch: ...]`.
* **Contracts**: Adhere strictly to all signatures defined in `!svc` and `!type`. Do not invent new endpoint names or change return types unless you patch the spec first.
* **Invariants**: Obey all `!rule` and `!invariant` declarations.

### Step 4: Run Verification Gates
If the task specifies a `[test: ...]` tag, run the verification gate:
```bash
aspec test project.aspec -t T<id>
```
Ensure all tests exit with status code `0`. If a test fails, debug and resolve the issue before proceeding.

### Step 5: Mark the Task Done
Mark the task as completed using the verification guard:
```bash
aspec patch project.aspec --set T<id>=done --verify
```
* If the verification gate passes, `agentspec` will update the status to `[x]`.
* If the test fails, `agentspec` will reject the transition and output the failure logs.

---

## 3. Subagent Delegation Protocol (For Orchestrator Swarms)

If you are acting as a lead agent or orchestrator delegating tasks to worker subagents:

1. **Never pass the full repository history or raw Markdown plan to a subagent.** This bloats subagent context windows and causes hallucinations.
2. **Use `aspec pack` to generate an isolated, minimal subagent prompt:**
   ```bash
   aspec pack project.aspec -t T3
   ```
   * `aspec pack` automatically prunes unrelated downstream tasks and removes unreferenced types and services, saving **60%–80% of prompt tokens**.
3. Pass the output of `aspec pack` directly into the subagent's prompt context.

---

## 4. State Mutation & Evolution Rules

As software develops, you may discover missing tasks, dependencies, or architectural requirements:

* **Append New Tasks**:
  ```bash
  aspec patch project.aspec --add-task "T6: integrate redis rate limiter [after: T2] [touch: src/limiter.py] [test: pytest tests/test_limiter.py]"
  ```
* **Document New Architectural Decisions**:
  If you choose a library or pattern, document the rationale so subsequent agents do not undo it:
  ```bash
  aspec patch project.aspec --add-why cache: "Redis sorted sets chosen for sliding-window rate limiting"
  ```
* **Enforce Integrity**:
  Before committing changes, ensure the spec has no orphaned tasks or broken dependencies:
  ```bash
  aspec lint project.aspec
  ```

---

## 5. Absolute Invariants for Agents

1. **No Manual Rewrites**: Always use `aspec patch` or `agentspec.patcher` to mutate state. Never overwrite the `.aspec` file with an unparsed string.
2. **Zero Invariant Deletion**: You are strictly forbidden from deleting or weakening `!rule` or `!invariant` entries without explicit, direct user instructions.
3. **No Out-of-Order Execution**: Never mark a task `in_progress` or `done` if its prerequisites in `[after: ...]` are not `[x] done`.
