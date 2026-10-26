# How to coordinate

You share this directory with other agents working at the same time. The project plan and all task state live in `project.aspec` (agentspec format). Use the `aspec` CLI for all task state changes; never edit `project.aspec` by hand.

Format: `!type` / `!svc` are contracts to implement exactly, `!rule` / `!invariant` are requirements you must follow. Tasks are `[ ]` todo, `[>]` in progress, `[x]` done. Task tags: `[after: ...]` prerequisites, `[touch: ...]` the only files you may edit, `[test: ...]` the acceptance command, `[by: ...]` the owner.

Loop:
1. `aspec ready project.aspec` and pick a task from Batch 1.
2. Claim it: `aspec patch project.aspec --set T<id>=in_progress@<your-name>`. If the claim is rejected, someone else has it or its files are in use; go back to step 1.
3. `aspec pack project.aspec -t T<id> --raw` shows the contracts and rules for your task.
4. Implement it, editing only the task's `[touch: ...]` files.
5. `aspec test project.aspec -t T<id>` until it passes.
6. Mark it done: `aspec patch project.aspec --set T<id>=done --verify`.
7. Repeat. If nothing is ready but tasks are still in progress or waiting on locks, run `sleep 20` and check again. Stop when every task is done.
