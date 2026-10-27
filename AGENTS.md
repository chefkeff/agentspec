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

Whenever you are assigned to implement features or advance the project, follow this 4-step lifecycle, using a unique agent name (e.g. `agent-3`) throughout:

```
                  ┌──────────────────────┐
                  │ 1. Get Next Task     │  aspec next <file> --as <name> --wait
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 2. Implement Feature │  Modify strictly within [touch: ...] files
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 3. Run Test Gate     │  aspec test <file> -t T<id>
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 4. Mark Complete     │  aspec patch <file> --set T<id>=done@<name> --verify
                  └──────────┬───────────┘
                             │
                             └──▶ back to 1 until `next` reports all tasks are done
```

### Step 1: Get Your Next Task
```bash
aspec next project.aspec --as <name> --wait
```
* `next` finds a ready task, claims it for you atomically and prints its scoped prompt: the contracts, rules and prerequisite tasks you need, the files you may edit, and the command to finish it.
* If you already hold a task, `next` gives you that task again rather than a new one.
* Your claim is a lease (30 minutes by default). Running `aspec next --as <name>` or `aspec test <file> -t T<id>` renews it. If it runs out, the task is released and another agent may take it.
* If it reports that no task is ready yet, run it again. If it reports that all tasks are done, stop.
* Orchestrators that assign work themselves can still use `aspec ready project.aspec --json` and claim with `aspec patch project.aspec --set T<id>=in_progress@<name>`.

### Step 2: Implement Within Scope
* **File Scoping**: Modify *only* the files declared in `[touch: ...]`. This is checked when you mark the task done.
* **Contracts**: Adhere strictly to all signatures defined in `!svc` and `!type`. Do not invent new endpoint names or change return types unless you patch the spec first.
* **Invariants**: Obey all `!rule` and `!invariant` declarations.

### Step 3: Run Verification Gates
If the task specifies a `[test: ...]` tag, run the verification gate:
```bash
aspec test project.aspec -t T<id>
```
Ensure all tests exit with status code `0`. If a test fails, debug and resolve the issue before proceeding.

### Step 4: Mark the Task Done
Mark the task as completed using the verification guard:
```bash
aspec patch project.aspec --set T<id>=done@<name> --verify
```
* `patch` first checks that, since you claimed the task, no files outside its `[touch: ...]` list changed (other agents' task files excepted); `--verify` then runs the test gate.
* `@<name>` makes the patch fail if your claim expired and the task was released or taken over. In that case, run `aspec next` again.
* If both pass, `agentspec` updates the status to `[x]`.
* If you changed files outside your scope, revert those changes and try again. If the test fails, `agentspec` rejects the transition and outputs the failure logs.
* To give a task back without finishing it: `aspec patch project.aspec --set T<id>=todo`.

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
3. **No Out-of-Order Execution**: Never mark a task `in_progress` or `done` if its prerequisites in `[after: ...]` are not `[x] done`. (`aspec next` and `aspec patch` enforce this.)
