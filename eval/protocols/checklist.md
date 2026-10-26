# How to coordinate

You share this directory with other agents working at the same time. The project plan is `PLAN.md`: contracts to implement exactly, constraints you must follow, and tasks with their prerequisites (`after:`), the only files you may edit, and a test command. Task state lives in `TODO.md`, a shared checklist; the statuses shown in `PLAN.md` are only a snapshot from the start.

`TODO.md` states: `- [ ] T3` todo, `- [~] T3 (agent-x)` in progress by agent-x, `- [x] T3` done.

Loop:
1. Read `TODO.md` and `PLAN.md`. Pick a todo task whose `after:` tasks are all `[x]` and whose files no in-progress task is editing.
2. Claim it by editing its line in `TODO.md` to `- [~] T<id> (<your-name>)`. Re-read `TODO.md` to confirm your claim is there; if another agent claimed it first, pick another task.
3. Implement it, editing only the task's listed files.
4. Run the task's test command until it passes.
5. Mark it done by changing its line to `- [x] T<id>`.
6. Repeat. If nothing is available but tasks are still in progress, run `sleep 20` and check again. Stop when every task is done.
