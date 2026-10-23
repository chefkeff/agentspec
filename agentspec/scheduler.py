from dataclasses import dataclass, field
from typing import List, Dict, Set
from .models import SpecDoc, TaskDef, TaskStatus

@dataclass
class ParallelBatch:
    batch_index: int
    tasks: List[TaskDef]
    touched_files: Set[str] = field(default_factory=set)

@dataclass
class TaskSchedule:
    ready_tasks: List[TaskDef]
    in_progress_tasks: List[TaskDef]
    blocked_tasks: List[TaskDef]
    completed_tasks: List[TaskDef]
    parallel_batches: List[ParallelBatch]
    file_conflicts: Dict[str, List[str]]  # filename -> list of task_ids contending for it

def get_task_schedule(doc: SpecDoc) -> TaskSchedule:
    """
    Computes execution readiness and conflict-free parallel execution batches
    for autonomous multi-agent swarms.
    """
    completed_tasks = [t for t in doc.tasks if t.status == TaskStatus.DONE]
    completed_ids = {t.id for t in completed_tasks}
    in_progress_tasks = [t for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS]

    ready_tasks: List[TaskDef] = []
    blocked_tasks: List[TaskDef] = []

    for t in doc.tasks:
        if t.status == TaskStatus.TODO:
            if all(dep in completed_ids for dep in t.dependencies):
                ready_tasks.append(t)
            else:
                blocked_tasks.append(t)

    # Detect file contention among all ready tasks
    file_to_tasks: Dict[str, List[str]] = {}
    for t in ready_tasks:
        for f in t.touches:
            file_to_tasks.setdefault(f, []).append(t.id)

    file_conflicts = {f: tids for f, tids in file_to_tasks.items() if len(tids) > 1}

    # Group ready tasks into conflict-free parallel execution batches (Greedy Graph Coloring)
    parallel_batches: List[ParallelBatch] = []
    remaining = list(ready_tasks)
    batch_idx = 1

    while remaining:
        current_batch_tasks: List[TaskDef] = []
        batch_touched: Set[str] = set()

        unpicked = []
        for t in remaining:
            task_touches = set(t.touches)
            # If task modifies files already claimed by this batch, defer to next batch
            if task_touches and (task_touches & batch_touched):
                unpicked.append(t)
            else:
                current_batch_tasks.append(t)
                batch_touched |= task_touches

        if not current_batch_tasks:
            # Fallback in case of degenerate condition
            current_batch_tasks = [unpicked.pop(0)]

        parallel_batches.append(ParallelBatch(
            batch_index=batch_idx,
            tasks=current_batch_tasks,
            touched_files=batch_touched
        ))
        batch_idx += 1
        remaining = unpicked

    return TaskSchedule(
        ready_tasks=ready_tasks,
        in_progress_tasks=in_progress_tasks,
        blocked_tasks=blocked_tasks,
        completed_tasks=completed_tasks,
        parallel_batches=parallel_batches,
        file_conflicts=file_conflicts
    )
