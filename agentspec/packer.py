import re
from typing import Set, List, Tuple
from .models import SpecDoc, TaskDef, TaskStatus, TypeDef, ServiceDef

def get_ancestor_task_ids(doc: SpecDoc, target_id: str) -> Set[str]:
    """Return all transitive dependency task IDs leading up to target_id."""
    adj = {t.id: t.dependencies for t in doc.tasks}
    if target_id not in adj:
        raise ValueError(f"Task '{target_id}' does not exist in spec.")

    ancestors = set()
    queue = list(adj[target_id])

    while queue:
        curr = queue.pop(0)
        if curr not in ancestors:
            ancestors.add(curr)
            queue.extend(adj.get(curr, []))

    return ancestors

def resolve_referenced_contracts(doc: SpecDoc, target_task: TaskDef) -> Tuple[List[TypeDef], List[ServiceDef]]:
    """
    Resolves minimal transitive types and services needed by target_task.
    Uses explicit [ref: ...] tags, or falls back to detecting names in task title.
    If no references are found, preserves all contracts.
    """
    type_names = {t.name for t in doc.types}
    svc_names = {s.name for s in doc.services}

    active_refs: Set[str] = set(target_task.refs)
    if not active_refs:
        # Auto-detect mentions in title
        for name in type_names | svc_names:
            if re.search(rf"\b{re.escape(name)}\b", target_task.title):
                active_refs.add(name)

    # If no specific references detected, keep all contracts
    if not active_refs:
        return list(doc.types), list(doc.services)

    # Compute transitive closure of types
    expanded_types: Set[str] = {r for r in active_refs if r in type_names}
    expanded_svcs: Set[str] = {r for r in active_refs if r in svc_names}

    # Pull types referenced in selected services
    for s in doc.services:
        if s.name in expanded_svcs:
            for m in s.methods:
                for tname in type_names:
                    if re.search(rf"\b{re.escape(tname)}\b", m.signature):
                        expanded_types.add(tname)

    # Transitive expansion over type definitions
    changed = True
    while changed:
        changed = False
        for t in doc.types:
            if t.name in expanded_types:
                for other_tname in type_names:
                    if other_tname not in expanded_types and re.search(rf"\b{re.escape(other_tname)}\b", t.definition):
                        expanded_types.add(other_tname)
                        changed = True

    pruned_types = [t for t in doc.types if t.name in expanded_types]
    pruned_svcs = [s for s in doc.services if s.name in expanded_svcs]
    return pruned_types, pruned_svcs

def pack_for_task(doc: SpecDoc, target_id: str, set_target_in_progress: bool = True, prune_contracts: bool = True) -> SpecDoc:
    """
    Slices the SpecDoc down to only the minimal causal dependencies for target_id.
    Excludes unrelated future tasks and optionally prunes unreferenced types and services.
    """
    ancestor_ids = get_ancestor_task_ids(doc, target_id)
    included_ids = ancestor_ids | {target_id}

    target_task = next(t for t in doc.tasks if t.id == target_id)

    # Filter tasks preserving original order
    sliced_tasks: List[TaskDef] = []
    for t in doc.tasks:
        if t.id in included_ids:
            new_status = t.status
            if t.id == target_id and set_target_in_progress:
                new_status = TaskStatus.IN_PROGRESS

            sliced_tasks.append(TaskDef(
                id=t.id,
                status=new_status,
                title=t.title,
                dependencies=list(t.dependencies),
                refs=list(t.refs),
                touches=list(t.touches),
                test_cmd=t.test_cmd,
                owner=t.owner
            ))

    if prune_contracts:
        types, services = resolve_referenced_contracts(doc, target_task)
    else:
        types, services = list(doc.types), list(doc.services)

    return SpecDoc(
        version=doc.version,
        meta=dict(doc.meta),
        types=types,
        services=services,
        invariants=list(doc.invariants),
        tasks=sliced_tasks
    )

def format_subagent_prompt(doc: SpecDoc, target_id: str, prune_contracts: bool = True) -> str:
    """
    Packages a focused, token-minimized subagent prompt for a specific task.
    """
    sliced_doc = pack_for_task(doc, target_id, prune_contracts=prune_contracts)
    target_task = next(t for t in sliced_doc.tasks if t.id == target_id)

    prompt = [
        f"You are assigned to complete Task {target_task.id}: \"{target_task.title}\".",
        "Below is your scoped context and architectural contract slice:",
        "",
        "```aspec",
        sliced_doc.to_aspec().strip(),
        "```",
        "",
        f"Instructions: Implement {target_task.id} adhering strictly to the above contracts and invariants."
    ]
    return "\n".join(prompt)

def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 90:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"

def format_next_message(result, spec_name: str) -> str:
    """Human/agent-readable outcome of `aspec next` (a patcher.NextResult)."""
    if result.status == "all_done":
        return "All tasks are done. Nothing left to claim."
    if result.status == "none_ready":
        in_progress = sum(t.status == TaskStatus.IN_PROGRESS for t in result.doc.tasks)
        todo = sum(t.status == TaskStatus.TODO for t in result.doc.tasks)
        lines = [f"No task is ready for you yet ({in_progress} in progress, {todo} waiting on prerequisites "
                 f"or file locks)."]
        release_in = getattr(result, "next_release_in", None)
        if release_in is not None:
            lines.append(f"The earliest claim can be released in about {_duration(release_in)} "
                         "if its owner does not renew it; finished tasks may free others sooner.")
        if getattr(result, "waited", False):
            lines.append("Run the same command again to keep waiting.")
        else:
            owner = getattr(result, "owner", None) or "<your-name>"
            lines.append(f"Wait with `aspec next {spec_name} --as {owner} --wait` instead of re-running "
                         "this command in a loop: it blocks until a task is ready.")
        return " ".join(lines)
    task = result.task
    verb = "Claimed" if result.status == "claimed" else "You already hold"
    released = (f"Released expired claim(s) on {', '.join(result.released)}.\n\n"
                if getattr(result, "released", None) else "")
    return released + "\n".join([
        f"{verb} {task.id} for {task.owner}.",
        "",
        format_subagent_prompt(result.doc, task.id),
        "",
        f"Edit only: {', '.join(task.touches) if task.touches else '(no [touch: ...] declared)'}",
        f"Your claim is a lease: running aspec next --as {task.owner} or aspec test {spec_name} -t {task.id} renews it.",
        f"When it is finished: aspec patch {spec_name} --set {task.id}=done@{task.owner} --verify",
    ])
