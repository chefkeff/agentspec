import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
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

def verify_mutations(doc: SpecDoc, mutations: List[str], spec_path: Optional[Path] = None,
                     run_gates: bool = True) -> None:
    """
    For every task the mutations would mark done: check that it only changed its
    [touch: ...] files since it was claimed (when spec_path is given and a claim
    snapshot exists), then, with run_gates, run its [test: ...] gate.
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
            if run_gates and task.test_cmd:
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
      - <task_id>=done[@owner]         (prerequisites must be done; with @owner, the
                                        task must still be claimed by that owner)
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
                if owner and not (target_task.status == TaskStatus.IN_PROGRESS and target_task.owner == owner):
                    if target_task.status == TaskStatus.DONE:
                        state = "it is already done"
                    elif target_task.status == TaskStatus.IN_PROGRESS:
                        state = f"it is now claimed by '{target_task.owner}'"
                    else:
                        state = "it is no longer claimed"
                    raise PatchError(
                        f"Cannot complete task '{task_id}' as '{owner}': {state}. "
                        "Your claim may have expired; run aspec next to get a task."
                    )
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

_TASK_LINE = re.compile(r"^\s*\[[ xX>]\]\s*([\w\.\-]+)\s*:")
_INV_LINE = re.compile(r"^\s*!(why|rule|invariant)\s")

def render_patched(original: str, before: SpecDoc, after: SpecDoc) -> str:
    """
    Write `after` by editing `original` line by line, so comments, blank lines and
    the formatting of untouched entries survive. Falls back to the canonical
    serialization if the edited text would not parse back to `after`.
    """
    lines = original.splitlines()
    task_lines = {}
    for i, line in enumerate(lines):
        m = _TASK_LINE.match(line)
        if m:
            task_lines[m.group(1)] = i

    old_tasks = {t.id: t for t in before.tasks}
    for t in after.tasks:
        if t.id in old_tasks and t.id in task_lines and t != old_tasks[t.id]:
            lines[task_lines[t.id]] = t.to_line()

    inserts = []  # (index, new lines); applied bottom-up so indices stay valid
    new_tasks = [t.to_line() for t in after.tasks if t.id not in old_tasks]
    if new_tasks:
        if task_lines:
            inserts.append((max(task_lines.values()) + 1, new_tasks))
        else:
            inserts.append((len(lines), ["", "# TASK EXECUTION DAG"] + new_tasks))
    new_invs = [inv.to_line() for inv in after.invariants[len(before.invariants):]]
    if new_invs:
        inv_lines = [i for i, line in enumerate(lines) if _INV_LINE.match(line)]
        if inv_lines:
            inserts.append((max(inv_lines) + 1, new_invs))
        else:
            header = [i for i, line in enumerate(lines) if line.startswith("@")]
            at = max(header) + 1 if header else 0
            inserts.append((at, ["", "# RATIONALES & INVARIANTS"] + new_invs))
    for at, new in sorted(inserts, key=lambda x: x[0], reverse=True):
        lines[at:at] = new

    text = "\n".join(lines).rstrip("\n") + "\n"
    try:
        if parse_spec(text) == after:
            return text
    except Exception:
        pass
    return after.to_aspec()

def lease_seconds_for(doc: SpecDoc, override: Optional[float] = None) -> float:
    """Claim lease length: the override, else '@meta lease: "30m"', else the default."""
    if override is not None:
        return float(override)
    raw = str(doc.meta.get("lease", "")).strip().lower()
    if raw:
        units = {"s": 1, "m": 60, "h": 3600}
        try:
            if raw[-1] in units:
                return float(raw[:-1]) * units[raw[-1]]
            return float(raw)
        except ValueError:
            raise PatchError(f"Invalid lease '{raw}' in @meta: use seconds or a number with s, m or h.")
    return scope.DEFAULT_LEASE_SECONDS

def _release_expired(filepath: Path, doc: SpecDoc, lease_seconds: float) -> List[str]:
    """Return expired claims to TODO (in `doc`) and forget their claim files."""
    released = []
    for task in scope.expired_claims(filepath, doc, lease_seconds):
        task.status, task.owner = TaskStatus.TODO, None
        scope.drop_claim(filepath, task.id)
        released.append(task.id)
    return released

def _next_release_in(filepath: Path, doc: SpecDoc, lease_seconds: float) -> Optional[float]:
    """Seconds until the earliest lease among in-progress tasks runs out, if any has one."""
    renewed = [scope.lease_renewed_at(filepath, t.id) for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS]
    renewed = [r for r in renewed if r is not None]
    if not renewed:
        return None
    return max(0.0, min(renewed) + lease_seconds - time.time())

def _status_mutations(mutations: List[str]) -> List[Tuple[str, TaskStatus, Optional[str]]]:
    return [_parse_status_mutation(m.strip()) for m in mutations
            if "=" in m and not m.strip().startswith("+")]

def _record_claims(filepath: Path, doc: SpecDoc, mutations: List[str]) -> List[str]:
    """
    Under the spec lock: renew leases of claimed tasks and forget finished or
    released ones. Returns the claimed task ids still needing a scope snapshot.
    """
    needs_snapshot = []
    for task_id, status, _ in _status_mutations(mutations):
        task = next((t for t in doc.tasks if t.id == task_id), None)
        if status == TaskStatus.IN_PROGRESS and task is not None:
            scope.renew_lease(filepath, task_id, task.owner)
            if not scope.snapshot_path(filepath, task_id).exists():
                needs_snapshot.append(task_id)
        elif status != TaskStatus.IN_PROGRESS:
            scope.drop_claim(filepath, task_id)
    return needs_snapshot

def _take_snapshots(filepath: Path, doc: SpecDoc, task_ids: List[str]) -> None:
    # Taken after the spec lock is released: hashing a large project should not
    # block other agents, and nobody else may edit a just-claimed task's files.
    for task_id in task_ids:
        task = next(t for t in doc.tasks if t.id == task_id)
        scope.take_snapshot(filepath, doc, task_id, task.owner)

def patch_file(filepath: Path, mutations: List[str], verify: bool = False,
               lease_seconds: Optional[float] = None) -> SpecDoc:
    """
    Apply mutations to a spec file under its lock. Tasks marked done are always
    checked against their [touch: ...] scope; with `verify` their [test: ...]
    gate must pass too. Claims let expired leases go first, so a task held by a
    vanished agent can be taken over.
    """
    # Run (possibly slow) checks before taking the lock so other agents aren't blocked.
    verify_mutations(parse_spec(filepath.read_text(encoding="utf-8")), mutations,
                     spec_path=filepath, run_gates=verify)

    with spec_lock(filepath):
        # Re-read under the lock: another agent may have patched the file meanwhile.
        original = filepath.read_text(encoding="utf-8")
        before = parse_spec(original)
        doc = parse_spec(original)
        if any(st == TaskStatus.IN_PROGRESS for _, st, _ in _status_mutations(mutations)):
            _release_expired(filepath, doc, lease_seconds_for(doc, lease_seconds))
        updated_doc = apply_mutations(doc, mutations)
        _atomic_write(filepath, render_patched(original, before, updated_doc))
        needs_snapshot = _record_claims(filepath, updated_doc, mutations)
    _take_snapshots(filepath, updated_doc, needs_snapshot)
    return updated_doc

@dataclass
class NextResult:
    status: str  # 'claimed', 'resumed', 'all_done' or 'none_ready'
    task: Optional[TaskDef]
    doc: SpecDoc
    released: List[str] = field(default_factory=list)  # expired claims returned to TODO
    owner: Optional[str] = None
    waited: bool = False
    # When nothing is ready: seconds until the earliest in-progress claim's lease runs out
    # (None if no in-progress task has a lease).
    next_release_in: Optional[float] = None

def claim_next(filepath: Path, owner: str, wait: bool = False, timeout: float = 90.0,
               poll_interval: float = 3.0, lease_seconds: Optional[float] = None) -> NextResult:
    """
    Atomically find and claim the next ready task for `owner`.

    If `owner` already holds an in-progress task, that task is returned instead
    ('resumed') and its lease renewed, so an agent never holds two tasks. Claims
    whose lease ran out are released first. With `wait`, keeps polling until a
    task becomes ready, every task is done, or `timeout` seconds pass.
    """
    if not owner:
        raise PatchError("An owner name is required to claim a task.")
    deadline = time.monotonic() + timeout
    released: List[str] = []
    while True:
        with spec_lock(filepath):
            original = filepath.read_text(encoding="utf-8")
            before = parse_spec(original)
            doc = parse_spec(original)
            held = next((t for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS and t.owner == owner), None)
            if held:
                scope.renew_lease(filepath, held.id, owner)
                return NextResult("resumed", held, doc, released, owner, wait)
            newly = _release_expired(filepath, doc, lease_seconds_for(doc, lease_seconds))
            released += newly
            if all(t.status == TaskStatus.DONE for t in doc.tasks):
                return NextResult("all_done", None, doc, released, owner, wait)
            schedule = get_task_schedule(doc)
            if schedule.ready_tasks:
                mutation = f"{schedule.ready_tasks[0].id}=in_progress@{owner}"
                updated = apply_mutations(doc, [mutation])
                _atomic_write(filepath, render_patched(original, before, updated))
                needs_snapshot = _record_claims(filepath, updated, [mutation])
                claimed = next(t for t in updated.tasks if t.id == schedule.ready_tasks[0].id)
            else:
                if newly:
                    _atomic_write(filepath, render_patched(original, before, doc))
                next_release_in = _next_release_in(filepath, doc, lease_seconds_for(doc, lease_seconds))
        if schedule.ready_tasks:
            _take_snapshots(filepath, updated, needs_snapshot)
            return NextResult("claimed", claimed, updated, released, owner, wait)
        if not wait or time.monotonic() >= deadline:
            return NextResult("none_ready", None, doc, released, owner, wait, next_release_in)
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

def renew_task_lease(filepath: Path, task_id: str) -> bool:
    """Renew the lease of an in-progress task (e.g. while its tests run). Returns False if it is not claimed."""
    with spec_lock(filepath):
        doc = parse_spec(filepath.read_text(encoding="utf-8"))
        task = next((t for t in doc.tasks if t.id == task_id), None)
        if task is None or task.status != TaskStatus.IN_PROGRESS:
            return False
        scope.renew_lease(filepath, task_id, task.owner)
        return True
