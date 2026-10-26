import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from agentspec.parser import parse_spec
from agentspec.models import TaskStatus
from agentspec.patcher import claim_next, patch_file, PatchError
from agentspec.scope import in_scope, snapshot_path
from agentspec.mcp import handle_tool_call

REPO_ROOT = Path(__file__).resolve().parent.parent

SPEC = """@spec 0.1
[x] T1: setup [touch: setup.py]
[ ] T2: auth [after: T1] [touch: src/auth.py]
[ ] T3: orders [after: T1] [touch: src/order.py, src/models/]
[ ] T4: audit auth [after: T1] [touch: src/auth.py]
[ ] T5: blocked [after: T2] [touch: src/five.py]
"""

@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "src" / "models").mkdir(parents=True)
    for name in ("auth.py", "order.py", "five.py", "shared.py"):
        (tmp_path / "src" / name).write_text("# start\n")
    (tmp_path / "src" / "models" / "base.py").write_text("# start\n")
    spec = tmp_path / "project.aspec"
    spec.write_text(SPEC, encoding="utf-8")
    return spec

def status(spec: Path, tid: str):
    t = next(t for t in parse_spec(spec.read_text()).tasks if t.id == tid)
    return t.status, t.owner

# --- aspec next -------------------------------------------------------------

def test_next_claims_first_ready_task(project: Path):
    res = claim_next(project, "agent-a")
    assert (res.status, res.task.id) == ("claimed", "T2")
    assert status(project, "T2") == (TaskStatus.IN_PROGRESS, "agent-a")
    assert snapshot_path(project, "T2").exists()

def test_next_resumes_held_task(project: Path):
    claim_next(project, "agent-a")
    res = claim_next(project, "agent-a")
    assert (res.status, res.task.id) == ("resumed", "T2")

def test_next_skips_tasks_whose_files_are_locked(project: Path):
    assert claim_next(project, "agent-a").task.id == "T2"
    # T4 shares src/auth.py with T2, so agent-b gets T3 and agent-c gets nothing
    assert claim_next(project, "agent-b").task.id == "T3"
    res = claim_next(project, "agent-c")
    assert res.status == "none_ready" and res.task is None

def test_next_reports_all_done(tmp_path: Path):
    spec = tmp_path / "p.aspec"
    spec.write_text("@spec 0.1\n[x] T1: only [touch: a.py]\n")
    assert claim_next(spec, "agent-a").status == "all_done"

def test_next_requires_owner(project: Path):
    with pytest.raises(PatchError, match="owner"):
        claim_next(project, "")

def test_next_wait_times_out(project: Path):
    claim_next(project, "agent-a")
    claim_next(project, "agent-b")
    start = time.monotonic()
    res = claim_next(project, "agent-c", wait=True, timeout=0.3, poll_interval=0.05)
    assert res.status == "none_ready"
    assert time.monotonic() - start >= 0.3

def test_next_wait_picks_up_released_task(project: Path):
    claim_next(project, "agent-a")  # T2
    claim_next(project, "agent-b")  # T3
    threading.Timer(0.2, lambda: patch_file(project, ["T2=todo"])).start()
    res = claim_next(project, "agent-c", wait=True, timeout=5, poll_interval=0.05)
    assert res.status == "claimed" and res.task.id in ("T2", "T4")

def test_concurrent_next_never_double_claims(project: Path):
    n = 6
    code = (
        "import sys; from pathlib import Path; from agentspec.patcher import claim_next\n"
        f"r = claim_next(Path({str(project)!r}), sys.argv[1])\n"
        "print(r.status, r.task.id if r.task else '-')\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, f"agent-{i}"], cwd=REPO_ROOT,
                              stdout=subprocess.PIPE, text=True) for i in range(n)]
    outs = [p.communicate(timeout=60)[0].split() for p in procs]
    claimed = [tid for st, tid in outs if st == "claimed"]
    assert sorted(claimed) == ["T2", "T3"]  # T4 is locked out by T2's src/auth.py
    assert sum(st == "none_ready" for st, _ in outs) == n - 2

def test_mcp_next(project: Path):
    out = handle_tool_call("aspec_next", {"file_path": str(project), "owner": "agent-a"})
    assert out.startswith("Claimed T2 for agent-a.")
    assert "aspec patch" in out and "--set T2=done --verify" in out

# --- scope check on done --verify -------------------------------------------

def test_in_scope_patterns():
    assert in_scope("src/auth.py", ["src/auth.py"])
    assert in_scope("src/models/base.py", ["src/models/"])
    assert in_scope("src/models/base.py", ["src/models"])
    assert in_scope("src/x.py", ["src/*.py"])
    assert not in_scope("src/modelsx.py", ["src/models"])
    assert not in_scope("tests/test_a.py", ["src/*.py"])

def test_done_accepts_in_scope_changes(project: Path):
    claim_next(project, "agent-a")
    (project.parent / "src" / "auth.py").write_text("def login(): ...\n")
    patch_file(project, ["T2=done"], verify=True)
    assert status(project, "T2")[0] == TaskStatus.DONE
    assert not snapshot_path(project, "T2").exists()

@pytest.mark.parametrize("change", ["modify", "create", "delete"])
def test_done_rejects_out_of_scope_changes(project: Path, change: str):
    claim_next(project, "agent-a")
    shared = project.parent / "src" / "shared.py"
    if change == "modify":
        shared.write_text("# hacked\n")
    elif change == "create":
        (project.parent / "src" / "extra.py").write_text("x = 1\n")
    else:
        shared.unlink()
    with pytest.raises(PatchError, match="outside its \\[touch: ...\\] list: src/(shared|extra).py"):
        patch_file(project, ["T2=done"], verify=True)
    assert status(project, "T2")[0] == TaskStatus.IN_PROGRESS

def test_done_allows_files_of_tasks_others_worked_on(project: Path):
    claim_next(project, "agent-a")  # T2
    claim_next(project, "agent-b")  # T3, claimed after T2
    (project.parent / "src" / "models" / "base.py").write_text("# by agent-b\n")
    (project.parent / "src" / "auth.py").write_text("# by agent-a\n")
    patch_file(project, ["T2=done"], verify=True)
    assert status(project, "T2")[0] == TaskStatus.DONE

def test_scope_not_checked_without_verify_or_snapshot(project: Path):
    # Claimed by an older agentspec (no snapshot) or completed without --verify
    patch_file(project, ["T2=in_progress@agent-a"])
    snapshot_path(project, "T2").unlink()
    (project.parent / "src" / "shared.py").write_text("# changed\n")
    patch_file(project, ["T2=done"], verify=True)
    assert status(project, "T2")[0] == TaskStatus.DONE

def test_undeclared_scope_is_not_checked(tmp_path: Path):
    spec = tmp_path / "p.aspec"
    spec.write_text("@spec 0.1\n[ ] T1: anything\n")
    claim_next(spec, "agent-a")
    (tmp_path / "anywhere.py").write_text("x = 1\n")
    patch_file(spec, ["T1=done"], verify=True)
    assert status(spec, "T1")[0] == TaskStatus.DONE

def test_scope_checked_before_test_gate(tmp_path: Path):
    spec = tmp_path / "p.aspec"
    marker = tmp_path / "gate_ran"
    spec.write_text(f"@spec 0.1\n[ ] T1: a [touch: a.py] [test: touch {marker}]\n")
    claim_next(spec, "agent-a")
    (tmp_path / "b.py").write_text("x = 1\n")
    with pytest.raises(PatchError, match="b.py"):
        patch_file(spec, ["T1=done"], verify=True)
    assert not marker.exists()

def test_release_drops_snapshot(project: Path):
    claim_next(project, "agent-a")
    patch_file(project, ["T2=todo"])
    assert not snapshot_path(project, "T2").exists()
