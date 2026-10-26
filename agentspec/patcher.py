import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Dict, Optional, Tuple
from .models import SpecDoc, TaskDef, TaskStatus, InvariantDef
from .parser import parse_spec, parse_task_tags
from .scheduler import conflicting_holders, get_task_schedule
from . import scope

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

class PatchError(Exception):
    pass

STATUS_ALIASES = {
    "done": TaskStatus.DONE, "x": TaskStatus.DONE,
    "in_progress": TaskStatus.IN_PROGRESS, "progress": TaskStatus.IN_PROGRESS, ">": TaskStatus.IN_PROGRESS,
    "todo": TaskStatus.TODO, "pending": TaskStatus.TODO, " ": TaskStatus.TODO,
}

def _parse_status_mutation(mut: str) -> Tuple[str, TaskStatus, Optional[str]]:
    """Split 'T2=in_progress@agent-a' into (task_id, status, owner)."""
    task_id, rhs = [x.strip() for x in mut.split("=", 1)]
    status_str, _, owner = rhs.partition("@")
    status = STATUS_ALIASES.get(status_str.strip().lower().replace("-", "_"))
    if status is None:
        raise PatchError(f"Invalid status '{rhs}' for task '{task_id}'")
    return task_id, status, owner.strip() or None

def _run_gate(task: TaskDef) -> None:
    res = subprocess.run(task.test_cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        err_msg = res.stderr.strip() or res.stdout.strip()
        raise PatchError(f"Verification test failed for task '{task.id}': {err_msg}")

def _check_scope(spec_path: Path, doc: SpecDoc, task: TaskDef) -> None:
    outside = scope.scope_violations(spec_path, doc, task)
    if outside:
        raise PatchError(
            f"Task '{task.id}' changed files outside its [touch: ...] list: {', '.join(outside)}. "
            "Revert those changes, or add the files to the task's [touch: ...] list."
        )

def verify_mutations(doc: SpecDoc, mutations: List[str], spec_path: Optional[Path] = None) -> None:
    """
    For every task the mutations would mark done: check that it only changed its
    [touch: ...] files since it was claimed (when spec_path is given and a claim
    snapshot exists), then run its [test: ...] gate.
    """
    task_map = {t.id: t for t in doc.tasks}
    for mut in mutations:
        mut = mut.strip()
        if "=" in mut and not mut.startswith("+"):
            task_id, status, _ = _parse_status_mutation(mut)
            task = task_map.get(task_id)
            if status != TaskStatus.DONE or not task:
                continue
            if spec_path is not None:
                _check_scope(spec_path, doc, task)
            if task.test_cmd:
                _run_gate(task)

def _check_prerequisites(task: TaskDef, task_map: Dict[str, TaskDef], action: str) -> None:
    pending = [d for d in task.dependencies if d not in task_map or task_map[d].status != TaskStatus.DONE]
    if pending:
        raise PatchError(f"Cannot {action} task '{task.id}': prerequisites not done: {', '.join(pending)}")

def apply_mutations(doc: SpecDoc, mutations: List[str], verify: bool = False) -> SpecDoc:
    """
    Apply a series of micro-mutations to an in-memory SpecDoc.
    Supported mutations:
      - <task_id>=in_progress[@owner]  (claim: task must be TODO, prerequisites done,
                                        and no file-lock conflict with in-progress tasks;
                                        re-claiming by the same owner is a no-op)
      - <task_id>=done                 (prerequisites must be done)
      - <task_id>=todo                 (release a claim)
      - +task <id>: <title> [after: <deps>] [ref: ...] [touch: ...] [test: ...]
      - +why <key>: "<content>"
      - +rule <key>: "<content>"
    """
    task_map: Dict[str, TaskDef] = {t.id: t for t in doc.tasks}

    for mut in mutations:
        mut = mut.strip()
        if not mut:
            continue

        # Status update: T2=done or T2=in_progress@agent-a
        if "=" in mut and not mut.startswith("+"):
            task_id, status, owner = _parse_status_mutation(mut)
            if task_id not in task_map:
                raise PatchError(f"Cannot update status: task '{task_id}' not found.")
            target_task = task_map[task_id]

            if status == TaskStatus.DONE:
                _check_prerequisites(target_task, task_map, "complete")
                if verify and target_task.test_cmd:
                    _run_gate(target_task)
                target_task.status = TaskStatus.DONE
            elif status == TaskStatus.IN_PROGRESS:
                if target_task.status == TaskStatus.IN_PROGRESS:
                    if owner and owner == target_task.owner:
                        continue
                    holder = f" by '{target_task.owner}'" if target_task.owner else ""
                    raise PatchError(f"Cannot claim task '{task_id}': already in progress{holder}.")
                if target_task.status == TaskStatus.DONE:
                    raise PatchError(f"Cannot claim task '{task_id}': already done. Set it to todo first to reopen it.")
                _check_prerequisites(target_task, task_map, "claim")
                in_progress = [t for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS]
                holders = conflicting_holders(target_task, in_progress)
                if holders:
                    raise PatchError(
                        f"Cannot claim task '{task_id}': file locks conflict with in-progress task(s) {', '.join(holders)}."
                    )
                target_task.status = TaskStatus.IN_PROGRESS
                target_task.owner = owner
            else:
                target_task.status = TaskStatus.TODO
                target_task.owner = None
            continue

        # Add task: +task T7: title [after: T5, T6] [ref: ...] [touch: ...] [test: ...]
        if mut.startswith("+task"):
            content = mut[len("+task"):].strip()
            task_match = re.match(r"^([\w\.\-]+)\s*:\s*(.+)$", content)
            if not task_match:
                raise PatchError(f"Invalid task syntax: '{mut}'. Expected: +task ID: Title [after: deps]")
            tid, rest = task_match.groups()
            if tid in task_map:
                raise PatchError(f"Task '{tid}' already exists in spec.")

            title, tags = parse_task_tags(rest)
            tags.pop("owner", None)  # new tasks start unclaimed
            new_task = TaskDef(id=tid.strip(), status=TaskStatus.TODO, title=title, **tags)
            doc.tasks.append(new_task)
            task_map[tid] = new_task
            continue

        # Add invariant: +why key: "content" or +rule key: "content"
        inv_match = re.match(r"^\+(why|rule|invariant)\s+([\w\.\-]+)\s*:\s*(.+)$", mut)
        if inv_match:
            kind, key, content = inv_match.groups()
            clean_content = content.strip().strip('"').strip("'")
            doc.invariants.append(InvariantDef(kind=kind, key=key.strip(), content=clean_content))
            continue

        raise PatchError(f"Unrecognized mutation: '{mut}'")

    # Validate DAG after patching
    dag_errors = doc.validate_dag()
    if dag_errors:
        raise PatchError(f"Patch created DAG errors: {'; '.join(dag_errors)}")

    return doc

@contextmanager
def spec_lock(filepath: Path) -> Iterator[None]:
    """
    Hold an exclusive lock on a sidecar '<file>.lock' so concurrent agents
    serialize their read-modify-write cycles. A sidecar is used because the
    spec itself is replaced atomically (new inode) on every write.
    """
    lock_path = filepath.with_name(filepath.name + ".lock")
    with open(lock_path, "a+b") as fh:
        if fcntl:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        else:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            else:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

def _atomic_write(filepath: Path, content: str) -> None:
    """Write via a temp file in the same directory and rename it into place."""
    fd, tmp_name = tempfile.mkstemp(dir=filepath.parent, prefix=f".{filepath.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        if filepath.exists():
            os.chmod(tmp_name, filepath.stat().st_mode & 0o7777)
        os.replace(tmp_name, filepath)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise

def _sync_snapshots(filepath: Path, doc: SpecDoc, mutations: List[str]) -> None:
    """Record a file snapshot for newly claimed tasks; drop it for finished or released ones."""
    for mut in mutations:
        mut = mut.strip()
        if "=" not in mut or mut.startswith("+"):
            continue
        task_id, status, owner = _parse_status_mutation(mut)
        if status == TaskStatus.IN_PROGRESS:
            if not scope.snapshot_path(filepath, task_id).exists():
                scope.take_snapshot(filepath, doc, task_id, owner)
        else:
            scope.drop_snapshot(filepath, task_id)

def patch_file(filepath: Path, mutations: List[str], verify: bool = False) -> SpecDoc:
    if verify:
        # Run (possibly slow) checks before taking the lock so other agents aren't blocked.
        verify_mutations(parse_spec(filepath.read_text(encoding="utf-8")), mutations, spec_path=filepath)

    with spec_lock(filepath):
        # Re-read under the lock: another agent may have patched the file meanwhile.
        doc = parse_spec(filepath.read_text(encoding="utf-8"))
        updated_doc = apply_mutations(doc, mutations)
        _atomic_write(filepath, updated_doc.to_aspec())
        _sync_snapshots(filepath, updated_doc, mutations)
    return updated_doc

@dataclass
class NextResult:
    status: str  # 'claimed', 'resumed', 'all_done' or 'none_ready'
    task: Optional[TaskDef]
    doc: SpecDoc

def claim_next(filepath: Path, owner: str, wait: bool = False, timeout: float = 90.0,
               poll_interval: float = 3.0) -> NextResult:
    """
    Atomically find and claim the next ready task for `owner`.

    If `owner` already holds an in-progress task, that task is returned instead
    ('resumed'), so an agent never holds two tasks. With `wait`, keeps polling
    until a task becomes ready, every task is done, or `timeout` seconds pass.
    """
    if not owner:
        raise PatchError("An owner name is required to claim a task.")
    deadline = time.monotonic() + timeout
    while True:
        with spec_lock(filepath):
            doc = parse_spec(filepath.read_text(encoding="utf-8"))
            held = next((t for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS and t.owner == owner), None)
            if held:
                return NextResult("resumed", held, doc)
            if all(t.status == TaskStatus.DONE for t in doc.tasks):
                return NextResult("all_done", None, doc)
            schedule = get_task_schedule(doc)
            if schedule.ready_tasks:
                task = schedule.ready_tasks[0]
                updated = apply_mutations(doc, [f"{task.id}=in_progress@{owner}"])
                _atomic_write(filepath, updated.to_aspec())
                _sync_snapshots(filepath, updated, [f"{task.id}=in_progress@{owner}"])
                claimed = next(t for t in updated.tasks if t.id == task.id)
                return NextResult("claimed", claimed, updated)
        if not wait or time.monotonic() >= deadline:
            return NextResult("none_ready", None, doc)
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
