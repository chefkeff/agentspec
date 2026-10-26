import subprocess
import sys
from pathlib import Path

import pytest
from agentspec.parser import parse_spec
from agentspec.models import TaskStatus
from agentspec.patcher import apply_mutations, patch_file, PatchError
from agentspec.scheduler import get_task_schedule
from agentspec.mcp import handle_tool_call

REPO_ROOT = Path(__file__).resolve().parent.parent

SPEC = """@spec 0.1
[x] T1: schema [touch: src/schema.sql]
[ ] T2: auth [after: T1] [touch: src/auth.py]
[ ] T3: orders [after: T1] [touch: src/order.py]
[ ] T4: audit auth [after: T1] [touch: src/auth.py, src/audit.py]
[ ] T5: blocked [after: T2] [touch: src/five.py]
"""

def get(doc, tid):
    return next(t for t in doc.tasks if t.id == tid)

# --- Guarded claims ---------------------------------------------------------

def test_claim_records_owner_and_round_trips():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@agent-a"])
    assert get(doc, "T2").status == TaskStatus.IN_PROGRESS
    assert get(doc, "T2").owner == "agent-a"

    reparsed = parse_spec(doc.to_aspec())
    assert get(reparsed, "T2").owner == "agent-a"
    assert get(reparsed, "T2").title == "auth"

def test_claim_rejected_when_already_claimed():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@agent-a"])
    with pytest.raises(PatchError, match="already in progress by 'agent-a'"):
        apply_mutations(doc, ["T2=in_progress@agent-b"])
    with pytest.raises(PatchError, match="already in progress"):
        apply_mutations(doc, ["T2=in_progress"])

def test_reclaim_by_same_owner_is_noop():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@agent-a"])
    apply_mutations(doc, ["T2=in_progress@agent-a"])
    assert get(doc, "T2").owner == "agent-a"

def test_claim_rejected_when_prerequisites_not_done():
    with pytest.raises(PatchError, match="prerequisites not done: T2"):
        apply_mutations(parse_spec(SPEC), ["T5=in_progress"])

def test_done_rejected_when_prerequisites_not_done():
    with pytest.raises(PatchError, match="Cannot complete task 'T5'"):
        apply_mutations(parse_spec(SPEC), ["T5=done"])

def test_claim_rejected_on_file_lock_conflict():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@agent-a"])
    with pytest.raises(PatchError, match="file locks conflict with in-progress task\\(s\\) T2"):
        apply_mutations(doc, ["T4=in_progress@agent-b"])
    # Disjoint files are fine
    apply_mutations(doc, ["T3=in_progress@agent-b"])
    assert get(doc, "T3").status == TaskStatus.IN_PROGRESS

def test_claim_rejected_on_done_task():
    with pytest.raises(PatchError, match="already done"):
        apply_mutations(parse_spec(SPEC), ["T1=in_progress"])

def test_release_clears_owner_and_frees_locks():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@agent-a", "T2=todo", "T4=in_progress@agent-b"])
    assert get(doc, "T2").owner is None
    assert get(doc, "T4").owner == "agent-b"

def test_sequential_mutations_see_earlier_ones():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@a", "T2=done", "T5=in_progress@a"])
    assert get(doc, "T5").status == TaskStatus.IN_PROGRESS

def test_added_task_cannot_be_preclaimed():
    doc = apply_mutations(parse_spec(SPEC), ["+task T6: new thing [after: T1] [by: sneaky]"])
    assert get(doc, "T6").owner is None
    assert get(doc, "T6").status == TaskStatus.TODO

# --- Scheduler lock gaps ----------------------------------------------------

def test_in_progress_locks_hold_back_ready_tasks():
    doc = apply_mutations(parse_spec(SPEC), ["T2=in_progress@agent-a"])
    schedule = get_task_schedule(doc)

    assert [t.id for t in schedule.ready_tasks] == ["T3"]
    assert [t.id for t in schedule.lock_waiting_tasks] == ["T4"]
    assert schedule.lock_holders == {"T4": ["T2"]}
    batched = {t.id for b in schedule.parallel_batches for t in b.tasks}
    assert "T4" not in batched

def test_undeclared_touches_are_exclusive_in_batches():
    spec = """@spec 0.1
[ ] T1: scoped a [touch: a.py]
[ ] T2: unscoped
[ ] T3: scoped b [touch: b.py]
"""
    schedule = get_task_schedule(parse_spec(spec))
    batches = [[t.id for t in b.tasks] for b in schedule.parallel_batches]
    assert batches == [["T1", "T3"], ["T2"]]

def test_in_progress_unscoped_task_blocks_everything():
    spec = """@spec 0.1
[>] T1: unscoped work
[ ] T2: scoped [touch: a.py]
"""
    schedule = get_task_schedule(parse_spec(spec))
    assert schedule.ready_tasks == []
    assert schedule.lock_holders == {"T2": ["T1"]}
    with pytest.raises(PatchError, match="conflict with in-progress task\\(s\\) T1"):
        apply_mutations(parse_spec(spec), ["T2=in_progress"])

# --- Locked, atomic file patching -------------------------------------------

def test_patch_file_preserves_mode_and_leaves_no_temp_files(tmp_path: Path):
    spec_file = tmp_path / "project.aspec"
    spec_file.write_text(SPEC, encoding="utf-8")
    spec_file.chmod(0o640)

    patch_file(spec_file, ["T2=in_progress@agent-a"])

    assert spec_file.stat().st_mode & 0o777 == 0o640
    assert "[>] T2: auth [after: T1] [touch: src/auth.py] [by: agent-a]" in spec_file.read_text()
    leftovers = {p.name for p in tmp_path.iterdir()} - {"project.aspec", "project.aspec.lock", "project.aspec.claims"}
    assert leftovers == set()

def test_failed_patch_leaves_file_untouched(tmp_path: Path):
    spec_file = tmp_path / "project.aspec"
    spec_file.write_text(SPEC, encoding="utf-8")
    with pytest.raises(PatchError):
        patch_file(spec_file, ["T3=in_progress@a", "T5=in_progress@a"])
    assert spec_file.read_text() == SPEC

def test_verify_gate_runs_before_lock_and_blocks_done(tmp_path: Path):
    spec_file = tmp_path / "project.aspec"
    spec_file.write_text("@spec 0.1\n[ ] T1: flaky [test: exit 1]\n", encoding="utf-8")
    with pytest.raises(PatchError, match="Verification test failed"):
        patch_file(spec_file, ["T1=done"], verify=True)
    assert get(parse_spec(spec_file.read_text()), "T1").status == TaskStatus.TODO

def _run_parallel(snippets):
    procs = [
        subprocess.Popen([sys.executable, "-c", code], cwd=REPO_ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for code in snippets
    ]
    return [(p.wait(timeout=60), p.stdout.read()) for p in procs]

def test_concurrent_patches_do_not_lose_updates(tmp_path: Path):
    spec_file = tmp_path / "swarm.aspec"
    spec_file.write_text("@spec 0.1\n[ ] T0: root\n", encoding="utf-8")
    n = 12
    snippets = [
        "from pathlib import Path; from agentspec.patcher import patch_file; "
        f"patch_file(Path({str(spec_file)!r}), ['+task N{i}: added by agent {i} [after: T0] [touch: f{i}.py]'])"
        for i in range(n)
    ]
    results = _run_parallel(snippets)
    assert all(code == 0 for code, _ in results)

    ids = {t.id for t in parse_spec(spec_file.read_text()).tasks}
    assert ids == {"T0"} | {f"N{i}" for i in range(n)}

def test_concurrent_claims_have_exactly_one_winner(tmp_path: Path):
    spec_file = tmp_path / "swarm.aspec"
    spec_file.write_text("@spec 0.1\n[ ] T1: contested [touch: hot.py]\n", encoding="utf-8")
    n = 8
    snippets = [
        "import sys; from pathlib import Path; from agentspec.patcher import patch_file, PatchError\n"
        f"try:\n    patch_file(Path({str(spec_file)!r}), ['T1=in_progress@agent-{i}'])\n    print('won')\n"
        "except PatchError:\n    print('lost')\n"
        for i in range(n)
    ]
    results = _run_parallel(snippets)
    outcomes = [out.strip() for _, out in results]
    assert outcomes.count("won") == 1
    assert outcomes.count("lost") == n - 1

    winner = outcomes.index("won")
    assert get(parse_spec(spec_file.read_text()), "T1").owner == f"agent-{winner}"

def test_mcp_patch_reports_rejection_as_text(tmp_path: Path):
    spec_file = tmp_path / "project.aspec"
    spec_file.write_text(SPEC, encoding="utf-8")
    out = handle_tool_call("aspec_patch", {"file_path": str(spec_file), "mutations": ["T5=in_progress"]})
    assert out.startswith("Patch rejected:")
