# How to coordinate

You share this directory with other agents working at the same time. The project plan and all task state live in `project.aspec` (agentspec format). Use the `aspec` CLI for all task state changes; never edit `project.aspec` by hand.

Format: `!type` / `!svc` are contracts to implement exactly, `!rule` / `!invariant` are requirements you must follow. Tasks are `[ ]` todo, `[>]` in progress, `[x]` done. Task tags: `[after: ...]` prerequisites, `[touch: ...]` the only files you may edit, `[test: ...]` the acceptance command, `[by: ...]` the owner.

Loop:
1. Get a task: `aspec next project.aspec --as <your-name> --wait`. It claims a ready task for you and prints its contracts, rules, the files you may edit and the command to finish it. If it says no task is ready yet, run it again. If it says all tasks are done, stop.
2. Implement it, editing only the task's `[touch: ...]` files.
3. `aspec test project.aspec -t T<id>` until it passes.
4. Mark it done: `aspec patch project.aspec --set T<id>=done --verify`. This rejects the task if you changed files outside its `[touch: ...]` list or its test fails.
5. To give a task back without finishing it: `aspec patch project.aspec --set T<id>=todo`.
6. Repeat from step 1.
