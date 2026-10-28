import re
import subprocess
import time
from pathlib import Path

import pytest
from agentspec.parser import parse_spec
from agentspec.models import TaskStatus
from agentspec.patcher import (claim_next, patch_file, renew_task_lease, lease_seconds_for,
                               render_patched, apply_mutations, PatchError)
from agentspec import scope

SPEC = """@spec 0.1
[x] T1: setup [touch: setup.py]
[ ] T2: auth [after: T1] [touch: src/auth.py]
[ ] T3: orders [after: T1] [touch: src/order.py]
"""

@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    for name in ("auth.py", "order.py", "shared.py"):
        (tmp_path / "src" / name).write_text("# start\n")
    spec = tmp_path / "project.aspec"
    spec.write_text(SPEC, encoding="utf-8")
    return spec

def task(spec: Path, tid: str):
    return next(t for t in parse_spec(spec.read_text()).tasks if t.id == tid)

def expire(spec: Path, tid: str, age: float = 4000):
    scope.renew_lease(spec, tid, task(spec, tid).owner, now=time.time() - age)

# --- Leases -----------------------------------------------------------------

def test_claim_writes_lease(project: Path):
    claim_next(project, "agent-a")
    assert scope.lease_renewed_at(project, "T2") == pytest.approx(time.time(), abs=5)

def test_expired_claim_is_released_and_taken_over(project: Path):
    claim_next(project, "agent-a")  # T2
    claim_next(project, "agent-b")  # T3
    expire(project, "T2")
    res = claim_next(project, "agent-c")
    assert (res.status, res.task.id, res.released) == ("claimed", "T2", ["T2"])
    assert task(project, "T2").owner == "agent-c"
    assert scope.snapshot_path(project, "T2").exists()

def test_fresh_claims_are_not_released(project: Path):
    claim_next(project, "agent-a")
    claim_next(project, "agent-b")
    res = claim_next(project, "agent-c")
    assert res.status == "none_ready" and res.released == []

def test_release_without_ready_task_is_written(project: Path):
    project.write_text(SPEC.replace("[touch: src/order.py]", "[touch: src/auth.py]"))
    claim_next(project, "agent-a")  # T2; T3 now waits on src/auth.py
    expire(project, "T2")
    res = claim_next(project, "agent-b")
    assert res.status == "claimed" and res.released == ["T2"]

def test_claims_without_lease_never_expire(project: Path):
    project.write_text(SPEC.replace("[ ] T2: auth [after: T1] [touch: src/auth.py]",
                                    "[>] T2: auth [after: T1] [touch: src/auth.py] [by: old-agent]"))
    res = claim_next(project, "agent-b")
    assert res.task.id == "T3" and task(project, "T2").owner == "old-agent"

def test_resume_renews_lease(project: Path):
    claim_next(project, "agent-a")
    expire(project, "T2", age=100)
    assert claim_next(project, "agent-a").status == "resumed"
    assert time.time() - scope.lease_renewed_at(project, "T2") < 5

def test_renew_task_lease(project: Path):
    assert renew_task_lease(project, "T2") is False  # not claimed
    claim_next(project, "agent-a")
    expire(project, "T2", age=100)
    assert renew_task_lease(project, "T2") is True
    assert time.time() - scope.lease_renewed_at(project, "T2") < 5

def test_patch_claim_takes_over_expired_lease(project: Path):
    patch_file(project, ["T2=in_progress@agent-a"])
    with pytest.raises(PatchError, match="already in progress by 'agent-a'"):
        patch_file(project, ["T2=in_progress@agent-b"])
    expire(project, "T2")
    patch_file(project, ["T2=in_progress@agent-b"])
    assert task(project, "T2").owner == "agent-b"

def test_lease_length_from_meta_and_override():
    doc = parse_spec('@spec 0.1\n@meta lease: "10m"\n')
    assert lease_seconds_for(doc) == 600
    assert lease_seconds_for(doc, 5) == 5
    assert lease_seconds_for(parse_spec("@spec 0.1\n")) == scope.DEFAULT_LEASE_SECONDS
    with pytest.raises(PatchError, match="Invalid lease"):
        lease_seconds_for(parse_spec('@spec 0.1\n@meta lease: "soon"\n'))

def test_done_with_owner_requires_current_claim(project: Path):
    claim_next(project, "agent-a")
    expire(project, "T2")
    claim_next(project, "agent-b")  # takes T2 over
    with pytest.raises(PatchError, match="now claimed by 'agent-b'"):
        patch_file(project, ["T2=done@agent-a"])
    patch_file(project, ["T2=done@agent-b"])
    assert task(project, "T2").status == TaskStatus.DONE
    assert not scope.lease_path(project, "T2").exists()

def test_done_with_owner_rejected_when_released(project: Path):
    claim_next(project, "agent-a")
    patch_file(project, ["T2=todo"])
    with pytest.raises(PatchError, match="no longer claimed"):
        patch_file(project, ["T2=done@agent-a"])

# --- Scope file listing -----------------------------------------------------

def test_build_dirs_are_not_hashed(tmp_path: Path):
    spec = tmp_path / "p.aspec"
    spec.write_text("@spec 0.1\n")
    for d in ("venv/lib", "build", "dist", "pkg.egg-info", ".venv", "src"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "f.py").write_text("x\n")
    assert set(scope.project_files(spec)) == {"src/f.py"}

def test_gitignored_files_are_not_hashed(tmp_path: Path):
    if subprocess.run(["git", "init", "-q", str(tmp_path)]).returncode != 0:
        pytest.skip("git not available")
    spec = tmp_path / "p.aspec"
    spec.write_text("@spec 0.1\n")
    (tmp_path / ".gitignore").write_text("out/\n")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "big.bin").write_text("x\n")
    (tmp_path / "app.py").write_text("x\n")
    assert set(scope.project_files(spec)) == {"app.py"}

def test_unchanged_files_reuse_cached_hash(tmp_path: Path):
    spec = tmp_path / "p.aspec"
    spec.write_text("@spec 0.1\n")
    (tmp_path / "a.py").write_text("x\n")
    first = scope.project_files(spec)
    fake = {"a.py": first["a.py"][:2] + ["cached"]}
    assert scope.project_files(spec, cache=fake)["a.py"][2] == "cached"

def test_snapshot_from_older_version_still_compares(project: Path):
    import hashlib, json
    claim_next(project, "agent-a")
    snap_file = scope.snapshot_path(project, "T2")
    snap = json.loads(snap_file.read_text())
    snap["files"] = {f: hashlib.sha1((project.parent / f).read_bytes()).hexdigest() for f in snap["files"]}
    snap_file.write_text(json.dumps(snap))
    (project.parent / "src" / "auth.py").write_text("def login(): ...\n")
    patch_file(project, ["T2=done"])
    assert task(project, "T2").status == TaskStatus.DONE

# --- Comment-preserving writes ----------------------------------------------

COMMENTED = """@spec 0.1

# Why we do things
!why db: "postgres"

# --- milestone 1 ---
[ ] T1: first [touch: a.py]   

# --- milestone 2 ---
[ ] T2: second [after: T1] [touch: b.py]
# trailing note
"""

def test_patch_keeps_comments_and_layout(tmp_path: Path):
    spec = tmp_path / "p.aspec"
    spec.write_text(COMMENTED)
    patch_file(spec, ["T1=in_progress@agent-a", "+task T3: third [after: T2] [touch: c.py]",
                      "+why cache: \"redis\""])
    lines = spec.read_text().splitlines()
    assert lines == [
        "@spec 0.1", "",
        "# Why we do things",
        '!why db: "postgres"',
        '!why cache: "redis"', "",
        "# --- milestone 1 ---",
        "[>] T1: first [touch: a.py] [by: agent-a]", "",
        "# --- milestone 2 ---",
        "[ ] T2: second [after: T1] [touch: b.py]",
        "[ ] T3: third [after: T2] [touch: c.py]",
        "# trailing note",
    ]

def test_first_invariant_and_task_get_sections(tmp_path: Path):
    before = parse_spec("@spec 0.1\n# just a comment\n")
    after = apply_mutations(parse_spec("@spec 0.1\n"), ['+why a: "b"', "+task T1: one"])
    text = render_patched("@spec 0.1\n# just a comment\n", before, after)
    assert "# just a comment" in text
    assert parse_spec(text) == after

# --- Waiting hints from next ------------------------------------------------

from agentspec.packer import format_next_message

def test_none_ready_reports_next_release_and_suggests_wait(project: Path):
    claim_next(project, "agent-a")
    claim_next(project, "agent-b")
    expire(project, "T2", age=1700)  # 100s left on the default 1800s lease
    res = claim_next(project, "agent-c")
    assert res.status == "none_ready"
    assert res.next_release_in == pytest.approx(100, abs=5)
    msg = format_next_message(res, "project.aspec")
    assert re.search(r"released in about 1m [34]\ds", msg)
    assert "aspec next project.aspec --as agent-c --wait" in msg

def test_none_ready_after_wait_says_run_again(project: Path):
    claim_next(project, "agent-a")
    claim_next(project, "agent-b")
    res = claim_next(project, "agent-c", wait=True, timeout=0.1, poll_interval=0.05)
    msg = format_next_message(res, "project.aspec")
    assert "Run the same command again" in msg and "--wait` instead" not in msg

def test_none_ready_without_leases_has_no_countdown(project: Path):
    project.write_text(SPEC.replace("[ ] T2: auth", "[>] T2: auth").replace("[ ] T3: orders", "[>] T3: orders"))
    res = claim_next(project, "agent-c")
    assert res.status == "none_ready" and res.next_release_in is None
    assert "released in" not in format_next_message(res, "project.aspec")
