"""
Claim bookkeeping for [touch: ...] file locks: scope snapshots and leases.

When a task is claimed, agentspec records a snapshot of the project files
(content hashes) next to the spec. When the task is marked done, the project
is compared against that snapshot. Any file that changed and is not covered
by the task's own [touch: ...] list, or by a task other agents worked on in
the meantime, is reported as out of scope.

Each claim also gets a lease. The lease is renewed whenever the owner runs
`aspec next` or `aspec test` for the task; a claim whose lease has run out is
released so another agent can pick the task up.

Paths in [touch: ...] are relative to the directory containing the spec and
may be exact files, directories, or fnmatch patterns (e.g. src/*.py).
"""
import fnmatch
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import SpecDoc, TaskDef, TaskStatus

# Generated or vendored directories never hashed when the project is not a git repo
# (in a git repo, .gitignore decides instead).
SKIP_DIRS = {"__pycache__", "node_modules", "venv", "build", "dist", "target", "site-packages"}
SKIP_SUFFIXES = (".pyc", ".pyo")
MAX_HASH_BYTES = 5 * 1024 * 1024
DEFAULT_LEASE_SECONDS = 1800.0

# A fingerprint is [size, mtime_ns, sha1 or None for files over MAX_HASH_BYTES].
Fingerprint = List


def claims_dir(spec_path: Path) -> Path:
    return spec_path.with_name(spec_path.name + ".claims")


def snapshot_path(spec_path: Path, task_id: str) -> Path:
    return claims_dir(spec_path) / f"{task_id}.json"


def lease_path(spec_path: Path, task_id: str) -> Path:
    return claims_dir(spec_path) / f"{task_id}.lease"


# --- File fingerprints ------------------------------------------------------

def _skipped(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p.startswith(".") for p in parts)
            or any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts[:-1])
            or rel.endswith(SKIP_SUFFIXES))


def _git_files(root: Path) -> Optional[List[str]]:
    """Tracked and untracked-but-not-ignored files, or None when root is not in a git work tree."""
    try:
        res = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return sorted({p for p in res.stdout.decode("utf-8", "surrogateescape").split("\0") if p})


def _walk_files(root: Path) -> List[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in filenames:
            out.append((Path(dirpath) / name).relative_to(root).as_posix())
    return out


def project_files(spec_path: Path, cache: Optional[Dict[str, Fingerprint]] = None) -> Dict[str, Fingerprint]:
    """
    Fingerprint every project file under the spec's directory, skipping hidden,
    ignored and generated files. Files whose size and mtime match `cache` reuse
    its hash instead of being read again.
    """
    root = spec_path.parent
    own = {spec_path.name, spec_path.name + ".lock"}
    claims = claims_dir(spec_path).name + "/"
    listed = _git_files(root)
    if listed is None:
        listed = _walk_files(root)
    cache = cache or {}

    files: Dict[str, Fingerprint] = {}
    for rel in listed:
        if rel in own or rel.startswith(claims) or _skipped(rel):
            continue
        full = root / rel
        try:
            st = full.stat()
        except OSError:
            continue  # deleted, or a listed path that is not a regular file
        if not full.is_file():
            continue
        prev = cache.get(rel)
        if isinstance(prev, list) and prev[0] == st.st_size and prev[1] == st.st_mtime_ns:
            files[rel] = prev
            continue
        digest = None
        if st.st_size <= MAX_HASH_BYTES:
            try:
                digest = hashlib.sha1(full.read_bytes()).hexdigest()
            except OSError:
                continue
        files[rel] = [st.st_size, st.st_mtime_ns, digest]
    return files


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, str) and isinstance(b, list):  # snapshot written by agentspec 0.3
        return a in (b[2], f"size:{b[0]}:mtime:{b[1]}")
    if not isinstance(a, list) or not isinstance(b, list):
        return a == b
    if a[2] is not None and b[2] is not None:
        return a[2] == b[2]
    return a[:2] == b[:2]


def _latest_snapshot_files(spec_path: Path) -> Dict[str, Fingerprint]:
    """File fingerprints from the most recent snapshot, used as a hash cache."""
    snaps = sorted(claims_dir(spec_path).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for snap in snaps:
        try:
            return json.loads(snap.read_text(encoding="utf-8"))["files"]
        except (OSError, ValueError, KeyError):
            continue
    return {}


# --- Snapshots ----------------------------------------------------------------

def take_snapshot(spec_path: Path, doc: SpecDoc, task_id: str, owner: Optional[str]) -> None:
    path = snapshot_path(spec_path, task_id)
    path.parent.mkdir(exist_ok=True)
    data = {
        "task": task_id,
        "owner": owner,
        "claimed_at": time.time(),
        "statuses": {t.id: t.status.value for t in doc.tasks},
        "files": project_files(spec_path, cache=_latest_snapshot_files(spec_path)),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def drop_claim(spec_path: Path, task_id: str) -> None:
    """Forget a task's snapshot and lease (it was finished or released)."""
    for path in (snapshot_path(spec_path, task_id), lease_path(spec_path, task_id)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# --- Leases -------------------------------------------------------------------

def renew_lease(spec_path: Path, task_id: str, owner: Optional[str], now: Optional[float] = None) -> None:
    path = lease_path(spec_path, task_id)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"owner": owner, "renewed_at": time.time() if now is None else now}),
                    encoding="utf-8")


def lease_renewed_at(spec_path: Path, task_id: str) -> Optional[float]:
    """When the task's lease was last renewed, or None for claims made without a lease."""
    try:
        return float(json.loads(lease_path(spec_path, task_id).read_text(encoding="utf-8"))["renewed_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def expired_claims(spec_path: Path, doc: SpecDoc, lease_seconds: float,
                   now: Optional[float] = None) -> List[TaskDef]:
    """In-progress tasks whose lease ran out. Claims without a lease file never expire."""
    now = time.time() if now is None else now
    out = []
    for t in doc.tasks:
        if t.status != TaskStatus.IN_PROGRESS:
            continue
        renewed = lease_renewed_at(spec_path, t.id)
        if renewed is not None and now - renewed > lease_seconds:
            out.append(t)
    return out


# --- Scope check --------------------------------------------------------------

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
    before: Dict[str, Fingerprint] = snap["files"]
    after = project_files(spec_path, cache=before)
    changed = {f for f in before.keys() | after.keys() if not _same(before.get(f), after.get(f))}

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
