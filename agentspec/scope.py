"""
Scope checking for [touch: ...] file locks.

When a task is claimed, agentspec records a snapshot of the project files
(content hashes) next to the spec. When the task is marked done with
--verify, the project is compared against that snapshot. Any file that
changed and is not covered by the task's own [touch: ...] list, or by a task
other agents worked on in the meantime, is reported as out of scope.

Paths in [touch: ...] are relative to the directory containing the spec and
may be exact files, directories, or fnmatch patterns (e.g. src/*.py).
"""
import fnmatch
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import SpecDoc, TaskDef, TaskStatus

SKIP_DIRS = {"__pycache__", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".pyo")
MAX_HASH_BYTES = 5 * 1024 * 1024


def claims_dir(spec_path: Path) -> Path:
    return spec_path.with_name(spec_path.name + ".claims")


def snapshot_path(spec_path: Path, task_id: str) -> Path:
    return claims_dir(spec_path) / f"{task_id}.json"


def _file_fingerprint(path: Path) -> str:
    st = path.stat()
    if st.st_size > MAX_HASH_BYTES:
        return f"size:{st.st_size}:mtime:{st.st_mtime_ns}"
    return hashlib.sha1(path.read_bytes()).hexdigest()


def project_files(spec_path: Path) -> Dict[str, str]:
    """Fingerprint every project file under the spec's directory, skipping hidden and generated files."""
    root = spec_path.parent
    own = {spec_path.name, spec_path.name + ".lock"}
    files: Dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS and d != claims_dir(spec_path).name]
        for name in filenames:
            if name.startswith(".") or name.endswith(SKIP_SUFFIXES):
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if rel in own:
                continue
            try:
                files[rel] = _file_fingerprint(full)
            except OSError:
                continue
    return files


def take_snapshot(spec_path: Path, doc: SpecDoc, task_id: str, owner: Optional[str]) -> None:
    path = snapshot_path(spec_path, task_id)
    path.parent.mkdir(exist_ok=True)
    data = {
        "task": task_id,
        "owner": owner,
        "claimed_at": time.time(),
        "statuses": {t.id: t.status.value for t in doc.tasks},
        "files": project_files(spec_path),
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def drop_snapshot(spec_path: Path, task_id: str) -> None:
    try:
        snapshot_path(spec_path, task_id).unlink()
    except FileNotFoundError:
        pass


def in_scope(path: str, touches: Iterable[str]) -> bool:
    for pattern in touches:
        pattern = pattern.strip().rstrip("/")
        if not pattern:
            continue
        if path == pattern or path.startswith(pattern + "/") or fnmatch.fnmatch(path, pattern):
            return True
    return False


def scope_violations(spec_path: Path, doc: SpecDoc, task: TaskDef) -> Optional[List[str]]:
    """
    Files changed since `task` was claimed that it was not allowed to touch.
    Returns None when there is no claim snapshot to compare against.
    """
    path = snapshot_path(spec_path, task.id)
    if not path.exists():
        return None
    if not task.touches:
        return []  # undeclared scope: nothing to enforce
    snap = json.loads(path.read_text(encoding="utf-8"))
    before: Dict[str, str] = snap["files"]
    after = project_files(spec_path)
    changed = {f for f in before.keys() | after.keys() if before.get(f) != after.get(f)}

    # Other tasks that were not finished when this one was claimed and have been
    # worked on since may legitimately have changed their own files.
    allowed = list(task.touches)
    for other in doc.tasks:
        if other.id == task.id:
            continue
        was = snap["statuses"].get(other.id)
        if was != TaskStatus.DONE.value and (was == TaskStatus.IN_PROGRESS.value or other.status != TaskStatus.TODO):
            if not other.touches:
                return []  # a task with undeclared scope may have changed anything
            allowed.extend(other.touches)
    return sorted(f for f in changed if not in_scope(f, allowed))
